from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import random
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.core.domain.embedding import EmbeddingPort
from app.core.domain.provider import ProviderInput, ProviderPort
from app.core.providers.openai_embedding_provider import (
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)
from app.core.providers.openai_provider import OpenAIProviderConfig
from app.core.settings import settings

from .costs import (
    PriceTable,
    StepCost,
    api_cost_per_correct_recall,
    embedding_cost,
    generation_cost,
    nullable_sum,
)
from .dataset import (
    ConversationFixture,
    EvaluationStep,
    TranscriptMessage,
    iter_exchange_pairs,
    load_dataset,
    sha256_file,
)
from .execution import ExecutionLedger, summarize_execution_ledger
from .memory import (
    BASE_SYSTEM_INSTRUCTIONS,
    ChunkingConfig,
    ComposedContext,
    ContextBudgets,
    ExactMemoryIndex,
    MemoryQuery,
    RetrievedChunk,
    VectorizedChunk,
    build_chunks,
    build_memory_query,
    compose_context,
    estimated_tokens,
    fit_latest_messages,
    stable_text_hash,
)
from .metrics import (
    aggregate,
    answer_metrics,
    echo_overlap,
    ranking_metrics,
    role_ranking_metrics,
)
from .providers import ConversationExperimentOpenAIProvider


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRATION = ROOT / "experiments/conversational_memory/registration.json"
INSTRUMENT_PATHS = (
    "experiments/conversational_memory/registration.json",
    "experiments/conversational_memory/dataset.py",
    "experiments/conversational_memory/memory.py",
    "experiments/conversational_memory/metrics.py",
    "experiments/conversational_memory/costs.py",
    "experiments/conversational_memory/execution.py",
    "experiments/conversational_memory/providers.py",
    "experiments/conversational_memory/run_experiment.py",
    "experiments/conversational_memory/data/dataset_manifest.json",
    "experiments/conversational_memory/data/development.jsonl",
    "experiments/conversational_memory/data/heldout.jsonl",
    "app/core/domain/embedding.py",
    "app/core/domain/provider.py",
    "app/core/providers/openai_embedding_provider.py",
    "app/core/providers/openai_provider.py",
)

MEMORY_ARMS = ("D1", "D2_JSON", "D2_TEXT")
ARMS = ("A", "B", "C", *MEMORY_ARMS)

REGISTERED_THRESHOLD_METRICS = {
    "minimum_d_over_c_recall_improvement": ("d_over_c_recall_improvement", "minimum"),
    "minimum_d_over_c_fact_consistency_improvement": (
        "d_over_c_fact_consistency_improvement",
        "minimum",
    ),
    "maximum_d_below_b_quality_loss": ("d_below_b_quality_loss", "maximum"),
    "minimum_d_vs_b_cumulative_api_cost_improvement": (
        "d_vs_b_cumulative_api_cost_improvement",
        "minimum",
    ),
    "primary_break_even_exchange": ("worst_break_even_exchange", "maximum"),
    "maximum_observed_retry_or_rebuild_cost_overhead": (
        "observed_retry_or_rebuild_cost_overhead",
        "maximum",
    ),
    "maximum_irrelevant_injection_rate": ("irrelevant_injection_rate", "maximum"),
    "maximum_duplicate_chunk_slot_rate": ("duplicate_chunk_slot_rate", "maximum"),
    "maximum_superseded_retrieval_rate": ("superseded_retrieval_rate", "maximum"),
    "maximum_repeated_source_amplification_rate": (
        "repeated_source_amplification_rate",
        "maximum",
    ),
    "minimum_message_recall_at_k": ("message_recall_at_k", "minimum"),
    "minimum_delivered_unique_source_recall": (
        "delivered_unique_source_recall",
        "minimum",
    ),
    "minimum_ambiguous_followup_recall_accuracy": (
        "ambiguous_followup_recall_accuracy",
        "minimum",
    ),
    "minimum_exact_identifier_recall_accuracy": (
        "exact_identifier_recall_accuracy",
        "minimum",
    ),
    "maximum_echo_overlap_p95": ("echo_overlap_p95", "maximum"),
    "maximum_p95_latency_regression_ms": ("p95_latency_regression_ms", "maximum"),
    "maximum_p95_ttft_regression_ms": ("p95_ttft_regression_ms", "maximum"),
}


class GuardFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_max_chars: int
    chunk_overlap_chars: int
    recent_window_max_messages: int
    retrieval_top_k_chunks: int
    similarity_threshold: float

    def key(self) -> str:
        return (
            f"chars={self.chunk_max_chars};overlap={self.chunk_overlap_chars};"
            f"window={self.recent_window_max_messages};topk={self.retrieval_top_k_chunks};"
            f"threshold={self.similarity_threshold:.4f}"
        )


@dataclass(frozen=True, slots=True)
class GenerationObservation:
    step_id: str
    arm: str
    repetition: int
    answer: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    ttft_ms: float | None
    provider: str
    model: str
    estimated_context_tokens: int
    conversational_recall_accuracy: float
    fact_consistency: float
    echo_overlap: float


def load_registration(path: Path, *, phase: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardFailure("registration is unavailable or invalid") from exc
    required = {
        "registration_version",
        "orq",
        "status",
        "question",
        "scope_note",
        "dataset",
        "instrument",
        "calibration",
        "budgets",
        "pricing",
        "primary_metrics",
        "decision_rule",
        "reporting",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise GuardFailure("registration schema differs from the instrument contract")
    if payload["orq"] != "ORQ-27" or payload["registration_version"] != 1:
        raise GuardFailure("registration identity is invalid")
    if payload["instrument"]["semantic_memory"] is not False:
        raise GuardFailure("semantic memory is outside ORQ-27")
    if phase == "heldout":
        _require_heldout_registration(path, payload)
    return payload


def verify_dataset(registration: Mapping[str, Any], *, phase: str) -> tuple[Path, list[ConversationFixture]]:
    split = "development" if phase == "development" else "heldout"
    manifest_path = ROOT / registration["dataset"]["manifest"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardFailure("dataset manifest is unavailable or invalid") from exc
    path = manifest_path.parent / manifest[split]["path"]
    expected = registration["dataset"][f"{split}_sha256"]
    actual = sha256_file(path)
    if manifest[split]["sha256"] != expected or actual != expected:
        raise GuardFailure(f"{split} dataset hash mismatch")
    fixtures = load_dataset(path, expected_split=split)
    expected_steps = manifest[split]["evaluation_steps"]
    if sum(len(fixture.evaluations) for fixture in fixtures) != expected_steps:
        raise GuardFailure("dataset evaluation-step count differs from manifest")
    return path, fixtures


def candidates(registration: Mapping[str, Any]) -> list[Candidate]:
    cfg = registration["calibration"]
    values = itertools.product(
        cfg["chunk_max_chars"],
        cfg["chunk_overlap_chars"],
        cfg["recent_window_max_messages"],
        cfg["retrieval_top_k_chunks"],
        cfg["similarity_threshold"],
    )
    result = [Candidate(*items) for items in values if items[1] < items[0]]
    if not result:
        raise GuardFailure("calibration candidate grid is empty")
    return result


def context_budgets(registration: Mapping[str, Any], *, recent_window: int) -> ContextBudgets:
    values = registration["budgets"]
    return ContextBudgets(
        total_input_tokens=values["total_input_tokens"],
        system_tokens=values["system_tokens"],
        conversation_tokens=values["conversation_tokens"],
        active_window_tokens=values["active_window_tokens"],
        episodic_memory_tokens=values["episodic_memory_tokens"],
        documentary_tokens=values["documentary_tokens"],
        current_user_tokens=values["current_user_tokens"],
        output_reserve_tokens=values["output_reserve_tokens"],
        recent_window_max_messages=recent_window,
    )


def chunking_config(registration: Mapping[str, Any], candidate: Candidate) -> ChunkingConfig:
    cfg = registration["calibration"]
    return ChunkingConfig(
        max_chars=candidate.chunk_max_chars,
        overlap_chars=candidate.chunk_overlap_chars,
        max_chunks_per_source_message=cfg["max_chunks_per_source_message"],
        index_version=cfg["index_version"],
    )


def collect_embedding_texts(
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    candidate_values: Sequence[Candidate],
) -> list[str]:
    texts: set[str] = set()
    chunk_pairs = sorted({(item.chunk_max_chars, item.chunk_overlap_chars) for item in candidate_values})
    windows = sorted({item.recent_window_max_messages for item in candidate_values})
    for fixture in fixtures:
        for max_chars, overlap in chunk_pairs:
            synthetic = Candidate(max_chars, overlap, windows[0], 1, 0.0)
            for chunk in build_chunks(
                tenant_id=fixture.tenant_id,
                conversation_id=fixture.conversation_id,
                messages=fixture.messages,
                config=chunking_config(registration, synthetic),
            ):
                texts.add(chunk.content)
        for current_user, _reference in iter_exchange_pairs(fixture):
            prefix = fixture.prefix_before(current_user.message_id)
            for window in windows:
                budgets = context_budgets(registration, recent_window=window)
                active = fit_latest_messages(
                    prefix,
                    max_tokens=budgets.active_window_tokens,
                    max_messages=window,
                )
                for variant in MEMORY_ARMS:
                    query = build_memory_query(
                        variant=variant,
                        current_user=current_user,
                        prefix=prefix,
                        active_messages=active,
                        max_tokens=registration["calibration"]["memory_query_max_tokens"],
                    )
                    if query.text is not None:
                        texts.add(query.text)
    return sorted(texts, key=lambda text: (stable_text_hash(text), text))


async def embed_texts(
    texts: Sequence[str],
    registration: Mapping[str, Any],
    *,
    embedding: EmbeddingPort | None = None,
    execution_ledger: ExecutionLedger | None = None,
) -> tuple[dict[str, tuple[float, ...]], dict[str, Any]]:
    if embedding is None:
        if not settings.openai_api_key:
            raise GuardFailure("OPENAI_API_KEY is required for Gate 1 embeddings")
        embedding = OpenAIEmbeddingProvider(
            OpenAIEmbeddingConfig(
                api_key=settings.openai_api_key,
                model=registration["instrument"]["embedding_model"],
                dimensions=registration["instrument"]["embedding_dimensions"],
                timeout_s=settings.provider_timeout_s,
                max_attempts=1,
            )
        )
    estimated_usage = sum(estimated_tokens(text) for text in texts)
    call = (
        execution_ledger.started(
            operation="embedding",
            model=registration["instrument"]["embedding_model"],
            estimated_tokens=estimated_usage,
        )
        if execution_ledger is not None
        else None
    )
    started = time.monotonic()
    try:
        result = await embedding.embed_many(texts)
    except Exception as exc:
        if call is not None:
            execution_ledger.failed(
                call,
                error_kind=type(exc).__name__,
                potentially_billable=True,
            )
        raise
    elapsed_ms = (time.monotonic() - started) * 1000
    if len(result.vectors) != len(texts):
        raise GuardFailure("embedding provider returned an unexpected vector count")
    expected_dimensions = registration["instrument"]["embedding_dimensions"]
    if result.dimensions != expected_dimensions or any(
        len(vector) != expected_dimensions for vector in result.vectors
    ):
        raise GuardFailure("embedding dimensions differ from registration")
    mapping = {text: tuple(float(value) for value in vector) for text, vector in zip(texts, result.vectors)}
    if call is not None:
        execution_ledger.succeeded(call, estimated_tokens=estimated_usage)
    return mapping, {
        "model": result.model,
        "dimensions": result.dimensions,
        "unique_texts": len(texts),
        "estimated_tokens": estimated_usage,
        "usage_provenance": "estimated",
        "api_calls": 1,
        "latency_ms": elapsed_ms,
        "vectors_sha256": _vectors_hash(mapping),
    }


def evaluate_candidate(
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    candidate: Candidate,
    vectors: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    per_variant: dict[str, list[dict[str, Any]]] = {
        variant: [] for variant in MEMORY_ARMS
    }
    isolation_failures = 0
    query_latency: list[float] = []
    for fixture in fixtures:
        source_roles = {message.message_id: message.role for message in fixture.messages}
        for evaluation in fixture.evaluations:
            current = fixture.message_by_id(evaluation.query_message_id)
            prefix = fixture.prefix_before(evaluation.query_message_id)
            budgets = context_budgets(registration, recent_window=candidate.recent_window_max_messages)
            active = fit_latest_messages(
                prefix,
                max_tokens=budgets.active_window_tokens,
                max_messages=candidate.recent_window_max_messages,
            )
            chunks = build_chunks(
                tenant_id=fixture.tenant_id,
                conversation_id=fixture.conversation_id,
                messages=prefix,
                config=chunking_config(registration, candidate),
            )
            index = ExactMemoryIndex(
                [VectorizedChunk(chunk=chunk, vector=tuple(vectors[chunk.content])) for chunk in chunks]
            )
            for variant in MEMORY_ARMS:
                query = build_memory_query(
                    variant=variant,
                    current_user=current,
                    prefix=prefix,
                    active_messages=active,
                    max_tokens=registration["calibration"]["memory_query_max_tokens"],
                )
                started = time.perf_counter()
                results = _retrieve(
                    index=index,
                    query=query,
                    fixture=fixture,
                    active=active,
                    candidate=candidate,
                    registration=registration,
                    vectors=vectors,
                )
                query_latency.append((time.perf_counter() - started) * 1000)
                metric = ranking_metrics(
                    results,
                    gold_source_message_ids=evaluation.gold_source_message_ids,
                    superseded_source_message_ids=evaluation.superseded_source_message_ids,
                    evaluation_top_k_messages=registration["calibration"]["evaluation_top_k_messages"],
                )
                roles = {
                    role: role_ranking_metrics(
                        results,
                        gold_source_message_ids=evaluation.gold_source_message_ids,
                        source_roles=source_roles,
                        role=role,
                        evaluation_top_k_messages=registration["calibration"]["evaluation_top_k_messages"],
                    )
                    for role in ("user", "assistant")
                }
                isolation_failures += sum(
                    result.chunk.tenant_id != fixture.tenant_id
                    or result.chunk.conversation_id != fixture.conversation_id
                    for result in results
                )
                per_variant[variant].append(
                    {
                        "step_id": evaluation.step_id,
                        "tenant_id": fixture.tenant_id,
                        "conversation_id": fixture.conversation_id,
                        "query_hash": query.normalized_query_hash,
                        "query_estimated_tokens": query.estimated_tokens,
                        "query_recent_sequences": list(query.included_source_sequences),
                        "zero_result_reason": query.zero_result_reason,
                        "relevance_order": [
                            {
                                "artifact_id": result.chunk.artifact_id,
                                "source_message_id": result.chunk.source_message_id,
                                "source_role": result.chunk.source_role,
                                "source_sequence": result.chunk.source_sequence,
                                "chunk_ordinal": result.chunk.chunk_ordinal,
                                "similarity": result.similarity,
                            }
                            for result in results
                        ],
                        "chronological_injection_source_sequences": sorted(
                            result.chunk.source_sequence for result in results
                        ),
                        "gold_source_message_ids": list(evaluation.gold_source_message_ids),
                        "irrelevant_source_message_ids": sorted(
                            {
                                result.chunk.source_message_id
                                for result in results
                                if result.chunk.source_message_id
                                not in evaluation.gold_source_message_ids
                            }
                        ),
                        "metrics": asdict(metric),
                        "role_metrics": roles,
                        "slices": list(evaluation.slices),
                    }
                )
    aggregate_by_variant = {
        variant: _aggregate_retrieval_rows(rows) for variant, rows in per_variant.items()
    }
    return {
        "candidate": asdict(candidate),
        "candidate_key": candidate.key(),
        "aggregate": aggregate_by_variant,
        "per_step": per_variant,
        "retrieval_cpu_ms": aggregate(query_latency),
        "isolation_failures": isolation_failures,
    }


def select_candidate(
    reports: Sequence[dict[str, Any]], registration: Mapping[str, Any]
) -> dict[str, Any]:
    safe = [report for report in reports if report["isolation_failures"] == 0]
    if not safe:
        raise GuardFailure("every calibration candidate violated isolation")
    thresholds = registration["decision_rule"]["thresholds"]
    retrieval_safe = [
        report
        for report in safe
        if all(
            report["aggregate"][variant]["irrelevant_memory_injection_rate"]
            <= thresholds["maximum_irrelevant_injection_rate"]
            and report["aggregate"][variant]["duplicate_chunk_slot_rate"]
            <= thresholds["maximum_duplicate_chunk_slot_rate"]
            and report["aggregate"][variant]["superseded_fact_retrieval_rate"]
            <= thresholds["maximum_superseded_retrieval_rate"]
            for variant in MEMORY_ARMS
        )
    ]
    if not retrieval_safe:
        raise GuardFailure("no candidate satisfies the registered retrieval safety ceilings")

    def ranking(report: dict[str, Any]) -> tuple[Any, ...]:
        aggregate_values = report["aggregate"]
        candidate = report["candidate"]
        return (
            -mean(aggregate_values[variant]["recall_at_k"] for variant in MEMORY_ARMS),
            -mean(aggregate_values[variant]["mrr"] for variant in MEMORY_ARMS),
            -mean(
                aggregate_values[variant]["delivered_unique_source_recall"]
                for variant in MEMORY_ARMS
            ),
            mean(
                aggregate_values[variant]["irrelevant_memory_injection_rate"]
                for variant in MEMORY_ARMS
            ),
            mean(
                aggregate_values[variant]["duplicate_chunk_slot_rate"]
                for variant in MEMORY_ARMS
            ),
            mean(
                aggregate_values[variant]["mean_query_estimated_tokens"]
                for variant in MEMORY_ARMS
            ),
            candidate["chunk_max_chars"],
            candidate["chunk_overlap_chars"],
            candidate["recent_window_max_messages"],
            candidate["retrieval_top_k_chunks"],
            candidate["similarity_threshold"],
        )

    return min(retrieval_safe, key=ranking)


async def run_managed_generation(
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    selected: Candidate,
    vectors: Mapping[str, Sequence[float]],
    *,
    provider: ProviderPort | None = None,
    execution_ledger: ExecutionLedger | None = None,
) -> list[GenerationObservation]:
    if provider is None:
        if not settings.openai_api_key:
            raise GuardFailure("OPENAI_API_KEY is required for managed generation")
        provider = ConversationExperimentOpenAIProvider(
            OpenAIProviderConfig(
                api_key=settings.openai_api_key,
                model=registration["instrument"]["generation_model"],
                timeout_s=settings.provider_timeout_s,
                max_attempts=1,
            )
        )
    observations: list[GenerationObservation] = []
    arms = ARMS
    ordinal = 0
    repetitions = registration["calibration"]["managed_generation_repetitions"]
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions <= 0:
        raise GuardFailure("managed_generation_repetitions must be a positive integer")
    for repetition in range(1, repetitions + 1):
        for fixture in fixtures:
            for evaluation in fixture.evaluations:
                current = fixture.message_by_id(evaluation.query_message_id)
                prefix = fixture.prefix_before(evaluation.query_message_id)
                contexts = _contexts_for_step(
                    fixture=fixture,
                    current=current,
                    prefix=prefix,
                    registration=registration,
                    selected=selected,
                    vectors=vectors,
                )
                rotated = arms[ordinal % len(arms) :] + arms[: ordinal % len(arms)]
                ordinal += 1
                for arm in rotated:
                    context, results = contexts[arm]
                    print(
                        f"generation repetition={repetition} step={evaluation.step_id} arm={arm}",
                        flush=True,
                    )
                    observation = await _generate_observation(
                        provider=provider,
                        fixture=fixture,
                        evaluation=evaluation,
                        context=context,
                        results=results,
                        execution_ledger=execution_ledger,
                        generation_model=registration["instrument"]["generation_model"],
                        repetition=repetition,
                    )
                    observations.append(observation)
    return observations


def build_cost_ledgers(
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    selected: Candidate,
    vectors: Mapping[str, Sequence[float]],
    generations: Sequence[GenerationObservation],
) -> dict[str, Any]:
    prices = _price_table(registration)
    observed: dict[tuple[str, str], list[GenerationObservation]] = defaultdict(list)
    for item in generations:
        observed[(item.step_id, item.arm)].append(item)
    ledgers: dict[str, Any] = {}
    for fixture in fixtures:
        evaluation_by_query = {
            step.query_message_id: step for step in fixture.evaluations
        }
        for arm in ARMS:
            steps: list[dict[str, Any]] = []
            cumulative_cost: float | None = 0.0
            cumulative_input = 0
            cumulative_output = 0
            for exchange_number, (current, reference) in enumerate(iter_exchange_pairs(fixture), start=1):
                prefix = fixture.prefix_before(current.message_id)
                contexts = _contexts_for_step(
                    fixture=fixture,
                    current=current,
                    prefix=prefix,
                    registration=registration,
                    selected=selected,
                    vectors=vectors,
                )
                context, _results = contexts[arm]
                evaluation = evaluation_by_query.get(current.message_id)
                generation_observations = (
                    observed.get((evaluation.step_id, arm)) if evaluation is not None else None
                )
                actual_inputs = [
                    item.input_tokens for item in generation_observations or []
                ]
                actual_outputs = [
                    item.output_tokens for item in generation_observations or []
                ]
                actual_input = (
                    sum(value for value in actual_inputs if value is not None) / len(actual_inputs)
                    if actual_inputs and all(value is not None for value in actual_inputs)
                    else None
                )
                actual_output = (
                    sum(value for value in actual_outputs if value is not None) / len(actual_outputs)
                    if actual_outputs and all(value is not None for value in actual_outputs)
                    else None
                )
                input_tokens = (
                    actual_input
                    if actual_input is not None
                    else context.estimated_input_tokens
                )
                output_tokens = (
                    actual_output
                    if actual_output is not None
                    else estimated_tokens(reference.content)
                )
                if generation_observations is None:
                    usage_provenance = "estimated"
                elif actual_input is not None and actual_output is not None:
                    usage_provenance = "actual"
                else:
                    usage_provenance = "mixed"
                query_tokens = 0
                index_tokens = 0
                if arm in MEMORY_ARMS:
                    budgets = context_budgets(
                        registration, recent_window=selected.recent_window_max_messages
                    )
                    active = fit_latest_messages(
                        prefix,
                        max_tokens=budgets.active_window_tokens,
                        max_messages=selected.recent_window_max_messages,
                    )
                    query = build_memory_query(
                        variant=arm,
                        current_user=current,
                        prefix=prefix,
                        active_messages=active,
                        max_tokens=registration["calibration"]["memory_query_max_tokens"],
                    )
                    query_tokens = query.estimated_tokens if query.text is not None else 0
                    newly_eligible = build_chunks(
                        tenant_id=fixture.tenant_id,
                        conversation_id=fixture.conversation_id,
                        messages=(current, reference),
                        config=chunking_config(registration, selected),
                    )
                    index_tokens = sum(estimated_tokens(chunk.content) for chunk in newly_eligible)
                cost = StepCost(
                    index_embedding_cost=embedding_cost(tokens=index_tokens, prices=prices),
                    query_embedding_cost=embedding_cost(tokens=query_tokens, prices=prices),
                    generation_api_cost=generation_cost(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        prices=prices,
                    ),
                    rebuild_embedding_cost=0.0,
                )
                step_total = cost.step_total_estimated_api_cost
                cumulative_cost = nullable_sum((cumulative_cost, step_total))
                cumulative_input += input_tokens
                cumulative_output += output_tokens
                steps.append(
                    {
                        "exchange": exchange_number,
                        "query_message_id": current.message_id,
                        "evaluation_step_id": evaluation.step_id if evaluation else None,
                        "usage_provenance": usage_provenance,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "index_embedding_estimated_tokens": index_tokens if arm in MEMORY_ARMS else "not_applicable",
                        "query_embedding_estimated_tokens": query_tokens if arm in MEMORY_ARMS else "not_applicable",
                        **asdict(cost),
                        "embedding_api_cost": cost.embedding_api_cost,
                        "step_total_estimated_api_cost": step_total,
                        "cumulative_conversation_api_cost": cumulative_cost,
                        "cumulative_input_tokens": cumulative_input,
                        "cumulative_output_tokens": cumulative_output,
                    }
                )
            repetitions = registration["calibration"]["managed_generation_repetitions"]
            correct = sum(
                item.conversational_recall_accuracy == 1.0
                for item in generations
                if item.arm == arm and item.step_id.startswith(fixture_step_prefix(fixture))
            ) / repetitions
            key = f"{fixture.conversation_id}:{arm}"
            ledgers[key] = {
                "tenant_id": fixture.tenant_id,
                "conversation_id": fixture.conversation_id,
                "arm": arm,
                "cost_basis": "logical_strategy_cost",
                "total_estimated_api_cost": cumulative_cost,
                "api_cost_per_correct_recall": api_cost_per_correct_recall(
                    total_cost=cumulative_cost,
                    correct_recall_count=correct,
                ),
                "correct_recall_count": correct,
                "steps": steps,
            }
    return ledgers


def compute_break_even(cost_ledgers: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for ledger in cost_ledgers.values():
        grouped[ledger["conversation_id"]][ledger["arm"]] = ledger
    result: dict[str, Any] = {}
    for conversation_id, arms in sorted(grouped.items()):
        baseline = arms["B"]["steps"]
        for memory_arm in MEMORY_ARMS:
            memory = arms[memory_arm]["steps"]
            break_even: int | None = None
            for index in range(len(baseline)):
                remaining = zip(baseline[index:], memory[index:])
                comparisons = []
                for baseline_step, memory_step in remaining:
                    baseline_cost = baseline_step["cumulative_conversation_api_cost"]
                    memory_cost = memory_step["cumulative_conversation_api_cost"]
                    comparisons.append(
                        baseline_cost is not None
                        and memory_cost is not None
                        and memory_cost <= baseline_cost
                    )
                if comparisons and all(comparisons):
                    break_even = index + 1
                    break
            result[f"{conversation_id}:{memory_arm}"] = {
                "conversation_id": conversation_id,
                "arm": memory_arm,
                "baseline": "B",
                "break_even_exchange": break_even,
            }
    return result


def summarize_generation(observations: Sequence[GenerationObservation]) -> dict[str, Any]:
    by_arm: dict[str, list[GenerationObservation]] = defaultdict(list)
    for observation in observations:
        by_arm[observation.arm].append(observation)
    return {
        arm: {
            "observations": len(items),
            "conversational_recall_accuracy": sum(
                item.conversational_recall_accuracy for item in items
            )
            / len(items),
            "fact_consistency": sum(item.fact_consistency for item in items) / len(items),
            "input_tokens": sum(
                item.input_tokens for item in items if item.input_tokens is not None
            ),
            "output_tokens": sum(
                item.output_tokens for item in items if item.output_tokens is not None
            ),
            "missing_input_usage": sum(item.input_tokens is None for item in items),
            "missing_output_usage": sum(item.output_tokens is None for item in items),
            "latency_ms": aggregate(
                [float(item.latency_ms) for item in items if item.latency_ms is not None]
            ),
            "ttft_ms": aggregate(
                [float(item.ttft_ms) for item in items if item.ttft_ms is not None]
            ),
            "echo_overlap": aggregate([item.echo_overlap for item in items]),
        }
        for arm, items in sorted(by_arm.items())
    }


def paired_bootstrap_interval(
    selected: Mapping[str, float],
    comparator: Mapping[str, float],
    *,
    step_clusters: Mapping[str, str],
    samples: int,
    seed: int,
) -> dict[str, float | int]:
    if set(selected) != set(comparator) or not selected:
        raise ValueError("paired samples must have the same non-empty step IDs")
    if set(step_clusters) != set(selected):
        raise ValueError("every paired step must belong to exactly one cluster")
    if samples <= 0:
        raise ValueError("samples must be positive")
    step_ids = sorted(selected)
    by_cluster: dict[str, list[float]] = defaultdict(list)
    for step_id in step_ids:
        by_cluster[step_clusters[step_id]].append(selected[step_id] - comparator[step_id])
    cluster_differences = [mean(by_cluster[key]) for key in sorted(by_cluster)]
    rng = random.Random(seed)
    draws = sorted(
        mean(rng.choice(cluster_differences) for _ in cluster_differences)
        for _ in range(samples)
    )
    return {
        "step_count": len(step_ids),
        "cluster_count": len(cluster_differences),
        "resampling_unit": "conversation",
        "samples": samples,
        "seed": seed,
        "mean_difference": mean(cluster_differences),
        "one_sided_ci95_low": _percentile(draws, 0.05),
    }


def evaluate_registered_thresholds(
    values: Mapping[str, float | int | None],
    thresholds: Mapping[str, float | int],
) -> dict[str, dict[str, Any]]:
    if set(thresholds) != set(REGISTERED_THRESHOLD_METRICS):
        raise GuardFailure("heldout threshold names differ from the registered instrument")
    clauses: dict[str, dict[str, Any]] = {}
    for threshold_name, (metric_name, direction) in REGISTERED_THRESHOLD_METRICS.items():
        value = values.get(metric_name)
        threshold = thresholds[threshold_name]
        if value is None:
            passed = False
        elif direction == "minimum":
            passed = value >= threshold
        else:
            passed = value <= threshold
        clauses[threshold_name] = {
            "metric": metric_name,
            "value": value,
            "operator": ">=" if direction == "minimum" else "<=",
            "threshold": threshold,
            "passed": passed,
        }
    return clauses


def build_heldout_decision(
    *,
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    selected_report: Mapping[str, Any],
    generations: Sequence[GenerationObservation],
    cost_ledgers: Mapping[str, Any],
    break_even: Mapping[str, Any],
    observed_execution: Mapping[str, Any],
    isolation_failures: int,
) -> dict[str, Any]:
    selected_arm = registration["calibration"]["selected_query_variant"]
    repetitions = registration["calibration"]["managed_generation_repetitions"]
    expected_steps = {
        evaluation.step_id: evaluation
        for fixture in fixtures
        for evaluation in fixture.evaluations
    }
    step_clusters = {
        evaluation.step_id: fixture.conversation_id
        for fixture in fixtures
        for evaluation in fixture.evaluations
    }
    observations: dict[tuple[str, str], list[GenerationObservation]] = defaultdict(list)
    for observation in generations:
        observations[(observation.step_id, observation.arm)].append(observation)
    coverage_failures: list[str] = []
    expected_repetitions = set(range(1, repetitions + 1))
    for step_id in sorted(expected_steps):
        for arm in ARMS:
            items = observations.get((step_id, arm), [])
            actual_repetitions = {item.repetition for item in items}
            if len(items) != repetitions or actual_repetitions != expected_repetitions:
                coverage_failures.append(f"{step_id}/{arm}")
    unexpected = sorted(
        f"{step_id}/{arm}"
        for step_id, arm in observations
        if step_id not in expected_steps or arm not in ARMS
    )
    coverage_failures.extend(f"unexpected:{item}" for item in unexpected)

    step_recall: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    step_consistency: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    if not coverage_failures:
        for step_id in expected_steps:
            for arm in ARMS:
                items = observations[(step_id, arm)]
                step_recall[arm][step_id] = mean(
                    item.conversational_recall_accuracy for item in items
                )
                step_consistency[arm][step_id] = mean(
                    item.fact_consistency for item in items
                )

    paired = registration["decision_rule"]["paired_evaluation"]
    bootstrap = (
        paired_bootstrap_interval(
            step_recall[selected_arm],
            step_recall["C"],
            step_clusters=step_clusters,
            samples=paired["bootstrap_samples"],
            seed=paired["bootstrap_seed"],
        )
        if not coverage_failures
        else None
    )
    quality = {
        arm: {
            "conversational_recall_accuracy": mean(step_recall[arm].values())
            if step_recall[arm]
            else None,
            "fact_consistency": mean(step_consistency[arm].values())
            if step_consistency[arm]
            else None,
        }
        for arm in ARMS
    }

    slices: dict[str, float | None] = {}
    for slice_name in ("ambiguous_followup", "exact_identifier"):
        step_ids = [
            step_id
            for step_id, evaluation in expected_steps.items()
            if slice_name in evaluation.slices
        ]
        slices[slice_name] = (
            mean(step_recall[selected_arm][step_id] for step_id in step_ids)
            if step_ids and not coverage_failures
            else None
        )

    logical_costs: dict[str, float | None] = {}
    for arm in ARMS:
        arm_costs = [
            ledger["total_estimated_api_cost"]
            for ledger in cost_ledgers.values()
            if ledger["arm"] == arm
        ]
        logical_costs[arm] = (
            mean(arm_costs)
            if arm_costs and all(value is not None for value in arm_costs)
            else None
        )
    selected_cost = logical_costs[selected_arm]
    baseline_cost = logical_costs["B"]
    cost_improvement = (
        1 - selected_cost / baseline_cost
        if selected_cost is not None and baseline_cost not in (None, 0)
        else None
    )
    break_even_values = [
        item["break_even_exchange"]
        for item in break_even.values()
        if item["arm"] == selected_arm
    ]
    worst_break_even = (
        max(break_even_values)
        if break_even_values and all(value is not None for value in break_even_values)
        else None
    )
    selected_retrieval = selected_report["aggregate"][selected_arm]
    generation = summarize_generation(generations)
    selected_generation = generation.get(selected_arm, {})
    recent_generation = generation.get("C", {})

    retry_count = observed_execution.get("retries")
    rebuild_cost = observed_execution.get("rebuild_embedding_cost")
    observed_overhead = 0.0 if retry_count == 0 and rebuild_cost == 0.0 else None

    values: dict[str, float | int | None] = {
        "d_over_c_recall_improvement": _difference(
            quality[selected_arm]["conversational_recall_accuracy"],
            quality["C"]["conversational_recall_accuracy"],
        ),
        "d_over_c_fact_consistency_improvement": _difference(
            quality[selected_arm]["fact_consistency"], quality["C"]["fact_consistency"]
        ),
        "d_below_b_quality_loss": _difference(
            quality["B"]["conversational_recall_accuracy"],
            quality[selected_arm]["conversational_recall_accuracy"],
        ),
        "d_vs_b_cumulative_api_cost_improvement": cost_improvement,
        "worst_break_even_exchange": worst_break_even,
        "observed_retry_or_rebuild_cost_overhead": observed_overhead,
        "irrelevant_injection_rate": selected_retrieval["irrelevant_memory_injection_rate"],
        "duplicate_chunk_slot_rate": selected_retrieval["duplicate_chunk_slot_rate"],
        "superseded_retrieval_rate": selected_retrieval["superseded_fact_retrieval_rate"],
        "repeated_source_amplification_rate": selected_retrieval[
            "repeated_source_amplification_rate"
        ],
        "message_recall_at_k": selected_retrieval["recall_at_k"],
        "delivered_unique_source_recall": selected_retrieval[
            "delivered_unique_source_recall"
        ],
        "ambiguous_followup_recall_accuracy": slices["ambiguous_followup"],
        "exact_identifier_recall_accuracy": slices["exact_identifier"],
        "echo_overlap_p95": _nested_value(selected_generation, "echo_overlap", "p95"),
        "p95_latency_regression_ms": _difference(
            _nested_value(selected_generation, "latency_ms", "p95"),
            _nested_value(recent_generation, "latency_ms", "p95"),
        ),
        "p95_ttft_regression_ms": _difference(
            _nested_value(selected_generation, "ttft_ms", "p95"),
            _nested_value(recent_generation, "ttft_ms", "p95"),
        ),
    }
    threshold_clauses = evaluate_registered_thresholds(
        values, registration["decision_rule"]["thresholds"]
    )
    automatic_clauses = {
        "tenant_and_conversation_isolation": {
            "value": isolation_failures,
            "expected": 0,
            "passed": isolation_failures == 0,
        },
        "complete_step_arm_repetition_coverage": {
            "value": coverage_failures,
            "expected": [],
            "passed": not coverage_failures,
        },
        "no_failed_or_unknown_api_calls": {
            "value": {
                "failed_calls": observed_execution.get("failed_calls"),
                "unknown_outcome_calls": observed_execution.get("unknown_outcome_calls"),
            },
            "expected": {"failed_calls": 0, "unknown_outcome_calls": 0},
            "passed": observed_execution.get("failed_calls") == 0
            and observed_execution.get("unknown_outcome_calls") == 0,
        },
        "complete_generation_usage": {
            "value": observed_execution.get("missing_success_usage_calls"),
            "expected": 0,
            "passed": observed_execution.get("missing_success_usage_calls") == 0,
        },
        "conversation_clustered_paired_recall_ci95_low_above_zero": {
            "value": None if bootstrap is None else bootstrap["one_sided_ci95_low"],
            "expected": "> 0",
            "passed": bootstrap is not None and bootstrap["one_sided_ci95_low"] > 0,
        },
    }
    all_passed = all(item["passed"] for item in threshold_clauses.values()) and all(
        item["passed"] for item in automatic_clauses.values()
    )
    return {
        "verdict": "GO" if all_passed else "STOP",
        "rule": "conjunctive_fail_closed",
        "selected_query_variant": selected_arm,
        "quality": quality,
        "conversation_clustered_paired_d_over_c_recall": bootstrap,
        "slice_recall_accuracy": slices,
        "logical_mean_conversation_api_cost": logical_costs,
        "values": values,
        "threshold_clauses": threshold_clauses,
        "automatic_clauses": automatic_clauses,
        "failed_clauses": [
            name
            for collection in (threshold_clauses, automatic_clauses)
            for name, item in collection.items()
            if not item["passed"]
        ],
    }


async def execute(
    *,
    phase: str,
    registration_path: Path,
    output_dir: Path,
    with_generation: bool,
) -> Path:
    if phase == "heldout" and not with_generation:
        raise GuardFailure("heldout execution requires managed generation")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    execution_ledger = ExecutionLedger(
        output_dir / "execution-ledger.jsonl",
        run_id=run_id,
        phase=phase,
    )
    registration = load_registration(registration_path, phase=phase)
    dataset_path, fixtures = verify_dataset(registration, phase=phase)
    if phase == "development":
        candidate_values = candidates(registration)
    else:
        candidate_values = [Candidate(**registration["calibration"]["frozen_parameters"])]
    texts = collect_embedding_texts(fixtures, registration, candidate_values)
    print(f"embedding unique_texts={len(texts)}", flush=True)
    vectors, embedding_observation = await embed_texts(
        texts,
        registration,
        execution_ledger=execution_ledger,
    )
    reports = []
    for index, candidate in enumerate(candidate_values, start=1):
        report = evaluate_candidate(fixtures, registration, candidate, vectors)
        reports.append(report)
        if index % 25 == 0 or index == len(candidate_values):
            print(f"calibration candidates={index}/{len(candidate_values)}", flush=True)
    selected_report = (
        select_candidate(reports, registration) if phase == "development" else reports[0]
    )
    selected = Candidate(**selected_report["candidate"])
    generation_observations: list[GenerationObservation] = []
    if with_generation:
        generation_observations = await run_managed_generation(
            fixtures,
            registration,
            selected,
            vectors,
            execution_ledger=execution_ledger,
        )
    cost_ledgers = build_cost_ledgers(
        fixtures,
        registration,
        selected,
        vectors,
        generation_observations,
    )
    recorded_at = datetime.now(timezone.utc).isoformat()
    price_table = _price_table(registration)
    generation_aggregate = summarize_generation(generation_observations)
    break_even = compute_break_even(cost_ledgers)
    observed_execution = {
        **summarize_execution_ledger(execution_ledger.path, run_id=run_id),
        "embedding_usage_provenance": "estimated",
        "retries": 0,
        "rebuild_embedding_cost": 0.0,
    }
    isolation_failures = sum(report["isolation_failures"] for report in reports)
    heldout_decision = (
        build_heldout_decision(
            fixtures=fixtures,
            registration=registration,
            selected_report=selected_report,
            generations=generation_observations,
            cost_ledgers=cost_ledgers,
            break_even=break_even,
            observed_execution=observed_execution,
            isolation_failures=isolation_failures,
        )
        if phase == "heldout"
        else None
    )
    result = {
        "schema_version": "conversation-memory-run-v1",
        "run_id": run_id,
        "recorded_at": recorded_at,
        "phase": phase,
        "decision_status": "THRESHOLDS_PENDING_OPERATOR_APPROVAL"
        if phase == "development"
        else heldout_decision["verdict"],
        "gate_scope": "Gate 1 offline only",
        "git_head": _git(["rev-parse", "HEAD"]),
        "registration_path": str(registration_path.relative_to(ROOT)),
        "registration_sha256": sha256_file(registration_path),
        "dataset_path": str(dataset_path.relative_to(ROOT)),
        "dataset_sha256": sha256_file(dataset_path),
        "teacher_forced_replay": True,
        "candidate_answers_indexed": False,
        "calibration_candidate_count": len(reports),
        "selected_candidate": selected_report,
        "candidate_leaderboard": sorted(
            (
                {
                    "candidate": report["candidate"],
                    "candidate_key": report["candidate_key"],
                    "aggregate": report["aggregate"],
                    "isolation_failures": report["isolation_failures"],
                }
                for report in reports
            ),
            key=lambda item: (
                -sum(
                    item["aggregate"][variant]["recall_at_k"]
                    for variant in MEMORY_ARMS
                ),
                item["candidate_key"],
            ),
        ),
        "embedding_observation": embedding_observation,
        "generation_enabled": with_generation,
        "generation_observations": [asdict(item) for item in generation_observations],
        "generation_aggregate": generation_aggregate,
        "cost_taxonomy": {
            "price_table": asdict(price_table),
            "logical_strategy_ledgers": cost_ledgers,
            "logical_break_even_vs_b": break_even,
            "observed_execution": observed_execution,
            "actual_experiment_cash_spend_note": "Physical embedding outputs were shared across D1/D2_JSON/D2_TEXT and the calibration grid; standalone arm ledgers do not discount that sharing.",
            "retrieval_cpu_time_is_not_monetized": True,
            "infrastructure_cost": None,
        },
        "storage": _storage_estimate(fixtures, registration, selected),
        "automatic_no_go_failures": {
            "tenant_or_conversation_isolation": isolation_failures
        },
        "heldout_decision": heldout_decision,
        "heldout_inspected": phase == "heldout",
    }
    output_path = output_dir / f"{phase}-{recorded_at.replace(':', '').replace('+00:00', 'Z')}-{run_id}.json"
    if output_path.exists():
        raise GuardFailure("append-only output collision")
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"run_path={output_path}", flush=True)
    return output_path


def _contexts_for_step(
    *,
    fixture: ConversationFixture,
    current: TranscriptMessage,
    prefix: Sequence[TranscriptMessage],
    registration: Mapping[str, Any],
    selected: Candidate,
    vectors: Mapping[str, Sequence[float]],
) -> dict[str, tuple[ComposedContext, tuple[RetrievedChunk, ...]]]:
    budgets = context_budgets(registration, recent_window=selected.recent_window_max_messages)
    active = fit_latest_messages(
        prefix,
        max_tokens=budgets.active_window_tokens,
        max_messages=selected.recent_window_max_messages,
    )
    chunks = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        messages=prefix,
        config=chunking_config(registration, selected),
    )
    index = ExactMemoryIndex(
        [VectorizedChunk(chunk=chunk, vector=tuple(vectors[chunk.content])) for chunk in chunks]
    )
    contexts: dict[str, tuple[ComposedContext, tuple[RetrievedChunk, ...]]] = {}
    for arm in ("A", "B", "C"):
        contexts[arm] = (
            compose_context(
                arm=arm,
                prefix=prefix,
                current_user=current,
                retrieved=(),
                budgets=budgets,
            ),
            (),
        )
    for arm in MEMORY_ARMS:
        query = build_memory_query(
            variant=arm,
            current_user=current,
            prefix=prefix,
            active_messages=active,
            max_tokens=registration["calibration"]["memory_query_max_tokens"],
        )
        results = _retrieve(
            index=index,
            query=query,
            fixture=fixture,
            active=active,
            candidate=selected,
            registration=registration,
            vectors=vectors,
        )
        contexts[arm] = (
            compose_context(
                arm=arm,
                prefix=prefix,
                current_user=current,
                retrieved=results,
                budgets=budgets,
            ),
            results,
        )
    return contexts


def _retrieve(
    *,
    index: ExactMemoryIndex,
    query: MemoryQuery,
    fixture: ConversationFixture,
    active: Sequence[TranscriptMessage],
    candidate: Candidate,
    registration: Mapping[str, Any],
    vectors: Mapping[str, Sequence[float]],
) -> tuple[RetrievedChunk, ...]:
    if query.text is None:
        return ()
    return index.search(
        vectors[query.text],
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        index_version=registration["calibration"]["index_version"],
        excluded_source_message_ids=(message.message_id for message in active),
        similarity_threshold=candidate.similarity_threshold,
        retrieval_top_k_chunks=candidate.retrieval_top_k_chunks,
        max_selected_chunks_per_source_message=registration["calibration"][
            "max_selected_chunks_per_source_message"
        ],
    )


async def _generate_observation(
    *,
    provider: ProviderPort,
    fixture: ConversationFixture,
    evaluation: EvaluationStep,
    context: ComposedContext,
    results: Sequence[RetrievedChunk],
    execution_ledger: ExecutionLedger | None,
    generation_model: str,
    repetition: int,
) -> GenerationObservation:
    request_id = uuid5(
        NAMESPACE_URL,
        f"orq27:{evaluation.step_id}:{context.arm}:repetition={repetition}",
    )
    provider_input = ProviderInput(request_id=request_id, messages=context.messages)
    call = (
        execution_ledger.started(
            operation="generation",
            model=generation_model,
            step_id=evaluation.step_id,
            arm=context.arm,
            estimated_tokens=context.estimated_input_tokens,
            repetition=repetition,
        )
        if execution_ledger is not None
        else None
    )
    started = time.monotonic()
    try:
        session = await provider.stream(provider_input)
    except Exception as exc:
        if call is not None:
            execution_ledger.failed(
                call,
                error_kind=type(exc).__name__,
                potentially_billable=False,
            )
        raise
    parts: list[str] = []
    first_token_at: float | None = None
    try:
        async for part in session.chunks:
            if first_token_at is None:
                first_token_at = time.monotonic()
            parts.append(part)
        final = await session.get_final_result()
    except Exception as exc:
        if call is not None:
            execution_ledger.failed(
                call,
                error_kind=type(exc).__name__,
                potentially_billable=True,
            )
        raise
    elapsed_ms = (time.monotonic() - started) * 1000
    result = final.provider_result
    answer = "".join(parts) or final.content
    if call is not None:
        execution_ledger.succeeded(
            call,
            actual_input_tokens=result.input_tokens,
            actual_output_tokens=result.output_tokens,
        )
    score = answer_metrics(answer, evaluation.expected)
    historical_assistant = [
        message.content
        for message in fixture.prefix_before(evaluation.query_message_id)
        if message.role == "assistant"
    ]
    return GenerationObservation(
        step_id=evaluation.step_id,
        arm=context.arm,
        repetition=repetition,
        answer=answer,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms if result.latency_ms is not None else int(elapsed_ms),
        ttft_ms=None if first_token_at is None else (first_token_at - started) * 1000,
        provider=result.provider,
        model=result.model_version,
        estimated_context_tokens=context.estimated_input_tokens,
        conversational_recall_accuracy=score.conversational_recall_accuracy,
        fact_consistency=score.fact_consistency,
        echo_overlap=echo_overlap(
            answer,
            historical_assistant,
            [retrieved.chunk.content for retrieved in results],
        ),
    )


def _aggregate_retrieval_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "delivered_unique_source_recall",
        "duplicate_chunk_slot_rate",
        "irrelevant_memory_injection_rate",
        "superseded_fact_retrieval_rate",
    )
    values: dict[str, Any] = {
        field: sum(row["metrics"][field] for row in rows) / len(rows) for field in fields
    }
    values["mean_query_estimated_tokens"] = sum(
        row["query_estimated_tokens"] for row in rows
    ) / len(rows)
    values["zero_result_rate"] = sum(
        not row["relevance_order"] for row in rows
    ) / len(rows)
    values["role_metrics"] = {}
    for role in ("user", "assistant"):
        values["role_metrics"][role] = {}
        for field in ("precision_at_k", "recall_at_k", "mrr"):
            role_values = [
                row["role_metrics"][role][field]
                for row in rows
                if row["role_metrics"][role][field] is not None
            ]
            values["role_metrics"][role][field] = (
                sum(role_values) / len(role_values) if role_values else None
            )
        values["role_metrics"][role]["gold_queries"] = sum(
            row["role_metrics"][role]["gold_count"] > 0 for row in rows
        )
        values["role_metrics"][role]["selected_chunks"] = sum(
            row["role_metrics"][role]["selected_chunks"] for row in rows
        )
    previous_irrelevant: dict[str, set[str]] = {}
    repeated = 0
    denominator = 0
    for row in rows:
        conversation_id = row["conversation_id"]
        current = set(row["irrelevant_source_message_ids"])
        if conversation_id in previous_irrelevant:
            repeated += len(current & previous_irrelevant[conversation_id])
            denominator += len(current)
        previous_irrelevant[conversation_id] = current
    values["repeated_source_amplification_rate"] = (
        repeated / denominator if denominator else 0.0
    )
    return values


def _price_table(registration: Mapping[str, Any]) -> PriceTable:
    price = registration["pricing"]
    instrument = registration["instrument"]
    return PriceTable(
        currency=price["currency"],
        effective_date=price["effective_date"],
        generation_model=instrument["generation_model"],
        generation_input_per_million=price["generation_input_per_million"],
        generation_output_per_million=price["generation_output_per_million"],
        embedding_model=instrument["embedding_model"],
        embedding_input_per_million=price["embedding_input_per_million"],
        source_urls=tuple(price["sources"]),
    )


def _storage_estimate(
    fixtures: Sequence[ConversationFixture],
    registration: Mapping[str, Any],
    selected: Candidate,
) -> dict[str, Any]:
    chunks = [
        chunk
        for fixture in fixtures
        for chunk in build_chunks(
            tenant_id=fixture.tenant_id,
            conversation_id=fixture.conversation_id,
            messages=fixture.messages,
            config=chunking_config(registration, selected),
        )
    ]
    content_bytes = sum(len(chunk.content.encode("utf-8")) for chunk in chunks)
    vector_bytes = len(chunks) * registration["instrument"]["embedding_dimensions"] * 4
    return {
        "artifact_count": len(chunks),
        "derived_content_bytes": content_bytes,
        "raw_float32_vector_bytes": vector_bytes,
        "minimum_content_plus_vector_bytes": content_bytes + vector_bytes,
        "database_row_and_index_overhead": None,
        "note": "Gate 1 has no PostgreSQL table; database and index overhead require Gate 2 measurement.",
    }


def fixture_step_prefix(fixture: ConversationFixture) -> str:
    return fixture.evaluations[0].step_id.split(":", 1)[0]


def _difference(left: float | int | None, right: float | int | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _nested_value(values: Mapping[str, Any], first: str, second: str) -> float | None:
    nested = values.get(first)
    if not isinstance(nested, Mapping):
        return None
    value = nested.get(second)
    return float(value) if isinstance(value, (int, float)) else None


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _vectors_hash(mapping: Mapping[str, Sequence[float]]) -> str:
    digest = hashlib.sha256()
    for text in sorted(mapping):
        digest.update(stable_text_hash(text).encode("ascii"))
        digest.update(b"\0")
        digest.update(
            json.dumps(list(mapping[text]), separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _require_heldout_registration(path: Path, payload: Mapping[str, Any]) -> None:
    decision = payload["decision_rule"]
    thresholds = decision["thresholds"]
    if payload["status"] != "heldout_approved" or decision["status"] != "approved":
        raise GuardFailure("heldout registration is not approved")
    if set(thresholds) != set(REGISTERED_THRESHOLD_METRICS):
        raise GuardFailure("heldout threshold names differ from the registered instrument")
    if any(value is None for value in thresholds.values()):
        raise GuardFailure("heldout decision thresholds are null")
    if not decision.get("approved_by") or not decision.get("approved_at"):
        raise GuardFailure("heldout registration is unsigned")
    frozen = payload["calibration"].get("frozen_parameters")
    if not isinstance(frozen, dict) or set(frozen) != {
        "chunk_max_chars",
        "chunk_overlap_chars",
        "recent_window_max_messages",
        "retrieval_top_k_chunks",
        "similarity_threshold",
    }:
        raise GuardFailure("heldout parameters are not frozen")
    try:
        candidate = Candidate(**frozen)
    except (TypeError, ValueError) as exc:
        raise GuardFailure("heldout parameters are invalid") from exc
    if candidate not in candidates(payload):
        raise GuardFailure("heldout parameters were not in the registered calibration grid")
    if payload["calibration"].get("selected_query_variant") not in set(MEMORY_ARMS):
        raise GuardFailure("heldout query variant is not frozen")
    paths = [str(path.relative_to(ROOT)), *INSTRUMENT_PATHS]
    for instrument_path in sorted(set(paths)):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", instrument_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if tracked.returncode:
            raise GuardFailure(f"heldout instrument is untracked: {instrument_path}")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *sorted(set(paths))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode or status.stdout.strip():
        raise GuardFailure("heldout instrument is modified or untracked")


def _git(args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise GuardFailure("git evidence unavailable")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ORQ-27 Gate 1 offline calibration/evaluation.")
    parser.add_argument("--phase", choices=("development", "heldout"), required=True)
    parser.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "experiments/conversational_memory/runs",
    )
    parser.add_argument("--with-generation", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(
            execute(
                phase=args.phase,
                registration_path=args.registration.resolve(),
                output_dir=args.output_dir.resolve(),
                with_generation=args.with_generation,
            )
        )
    except GuardFailure as exc:
        print(f"RESULT gate1=blocked reason={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
