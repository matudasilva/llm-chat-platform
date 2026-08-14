from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence
from uuid import uuid4

from app.core.providers.openai_provider import OpenAIProviderConfig
from app.core.settings import settings

from .dataset import (
    ConversationFixture,
    EvaluationStep,
    load_dataset,
    verify_dataset_manifest,
)
from .external import (
    DevelopmentOpenAIProvider,
    GenerationResult,
    SemanticExtractor,
    curated_facts,
    embed_texts,
    generate_streamed,
)
from .memory import (
    ComposedInput,
    MemoryChunk,
    RankedChunk,
    RetrievalProfile,
    SemanticFact,
    bm25_search,
    build_chunks,
    build_query,
    compose_input,
    current_semantic_facts,
    estimated_tokens,
    exact_dense_search,
    fallback_reasons,
    generate_profiles,
    reciprocal_rank_fusion,
    stable_hash,
)
from .protocol import (
    DEFAULT_MANIFEST,
    ExternalCallLedger,
    ProtocolError,
    instrument_hashes,
    load_manifest,
    sha256_file,
    verify_origin,
)
from .scorers import (
    aggregate,
    answer_score,
    echo_overlap,
    fallback_confusion,
    retrieval_score,
    role_retrieval_score,
    semantic_extraction_score,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
RUNS = PACKAGE / "runs"
ARMS = (
    "A", "B", "C", "D-EVT", "E-EVT", "F-MSG", "F-EVT",
    "G-SEM", "G-ADAPT", "G-FALLBACK", "R",
)
INSTRUMENT_FILES = (
    "__init__.py",
    "README.md",
    "development-manifest.json",
    "protocol.py",
    "dataset.py",
    "build_dataset.py",
    "memory.py",
    "external.py",
    "scorers.py",
    "run_development.py",
    "data/dataset-manifest.json",
    "data/authoring.jsonl",
    "data/development.jsonl",
)


class DevelopmentInvalid(RuntimeError):
    """The single authorized development execution is invalid and terminal."""


def _key(fixture: ConversationFixture, evaluation: EvaluationStep) -> str:
    return f"{fixture.conversation_id}:{evaluation.step_id}"


def _profile_assets(
    fixtures: Sequence[ConversationFixture],
    profiles: Sequence[RetrievalProfile],
) -> tuple[
    dict[tuple[str, str, str], tuple[MemoryChunk, ...]],
    dict[tuple[str, str, str], str],
    list[str],
]:
    chunks: dict[tuple[str, str, str], tuple[MemoryChunk, ...]] = {}
    queries: dict[tuple[str, str, str], str] = {}
    embedding_texts: list[str] = []
    for fixture in fixtures:
        for profile in profiles:
            for unit in ("event", "message"):
                values = build_chunks(
                    tenant_id=fixture.tenant_id,
                    conversation_id=fixture.conversation_id,
                    events=fixture.events,
                    unit_type=unit,
                    profile=profile.chunk,
                    index_version=f"orq29-{profile.profile_id}-{unit}",
                )
                chunks[(fixture.conversation_id, profile.profile_id, unit)] = values
                embedding_texts.extend(item.text for item in values)
            for evaluation in fixture.evaluations:
                prefix = fixture.prefix_before(evaluation.query_event_id)
                current, _ = fixture.query_and_reference(evaluation)
                for variant in ("Q1", "Q2-TEXT"):
                    query = build_query(
                        variant=variant,
                        current_user=current,
                        prefix=prefix,
                        recent_event_count=profile.active_window_events,
                        max_tokens=profile.query_tokens,
                    )
                    queries[(evaluation.step_id, profile.profile_id, variant)] = query.text
                    embedding_texts.append(query.text)
    return chunks, queries, embedding_texts


async def _embed_all(
    *,
    texts: Sequence[str],
    api_key: str,
    manifest: Mapping[str, Any],
    ledger: ExternalCallLedger,
) -> dict[str, tuple[float, ...]]:
    unique = tuple(dict.fromkeys(texts))
    vectors: dict[str, tuple[float, ...]] = {}
    batch_size = int(manifest["execution"]["embedding_batch_size"])
    for start in range(0, len(unique), batch_size):
        batch = unique[start:start + batch_size]
        values = await embed_texts(
            texts=batch,
            api_key=api_key,
            model=manifest["dense"]["model"],
            dimensions=int(manifest["dense"]["dimensions"]),
            ledger=ledger,
            step_id=f"embedding-batch-{start // batch_size:03d}",
        )
        vectors.update(values)
    if len(vectors) != len(unique):
        raise DevelopmentInvalid("not every frozen text received an embedding")
    return vectors


def _retrieve(
    *,
    fixture: ConversationFixture,
    evaluation: EvaluationStep,
    profile: RetrievalProfile,
    chunks: Mapping[tuple[str, str, str], tuple[MemoryChunk, ...]],
    queries: Mapping[tuple[str, str, str], str],
    vectors: Mapping[str, Sequence[float]],
    unit: str,
    variant: str = "Q2-TEXT",
) -> dict[str, tuple[RankedChunk, ...]]:
    query_text = queries[(evaluation.step_id, profile.profile_id, variant)]
    query_vector = vectors[stable_hash(query_text)]
    prefix = fixture.prefix_before(evaluation.query_event_id)
    active = prefix[-profile.active_window_events:]
    excluded = {event.event_id for event in active}
    query_event = fixture.event_by_id(evaluation.query_event_id)
    corpus = chunks[(fixture.conversation_id, profile.profile_id, unit)]
    dense = exact_dense_search(
        corpus,
        vectors,
        query_vector,
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=query_event.sequence,
        excluded_event_ids=excluded,
        threshold=profile.dense_threshold,
        limit=profile.candidate_depth,
    )
    lexical = bm25_search(
        corpus,
        query_text,
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=query_event.sequence,
        excluded_event_ids=excluded,
        k1=profile.bm25_k1,
        b=profile.bm25_b,
        limit=profile.candidate_depth,
    )
    hybrid = reciprocal_rank_fusion(
        dense,
        lexical,
        constant=profile.rrf_c,
        top_k=profile.top_k,
    )
    return {
        "dense": dense[:profile.top_k],
        "lexical": lexical[:profile.top_k],
        "hybrid": hybrid,
    }


def _calibrate_profiles(
    *,
    fixtures: Sequence[ConversationFixture],
    profiles: Sequence[RetrievalProfile],
    chunks: Mapping[tuple[str, str, str], tuple[MemoryChunk, ...]],
    queries: Mapping[tuple[str, str, str], str],
    vectors: Mapping[str, Sequence[float]],
) -> tuple[RetrievalProfile, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        scores: dict[str, list[Any]] = defaultdict(list)
        query_tokens: list[int] = []
        retrieval_latency_ms: list[float] = []
        for fixture in fixtures:
            for evaluation in fixture.evaluations:
                retrieval_started = time.perf_counter()
                event_results = _retrieve(
                    fixture=fixture,
                    evaluation=evaluation,
                    profile=profile,
                    chunks=chunks,
                    queries=queries,
                    vectors=vectors,
                    unit="event",
                )
                message_results = _retrieve(
                    fixture=fixture,
                    evaluation=evaluation,
                    profile=profile,
                    chunks=chunks,
                    queries=queries,
                    vectors=vectors,
                    unit="message",
                )
                retrieval_latency_ms.append(
                    (time.perf_counter() - retrieval_started) * 1000
                )
                for name, result in (
                    ("dense_event", event_results["dense"]),
                    ("bm25_event", event_results["lexical"]),
                    ("hybrid_event", event_results["hybrid"]),
                    ("hybrid_message", message_results["hybrid"]),
                ):
                    scores[name].append(
                        retrieval_score(
                            result,
                            evaluation=evaluation,
                            evaluation_top_k_events=profile.top_k,
                        )
                    )
                query_tokens.append(
                    estimated_tokens(queries[(evaluation.step_id, profile.profile_id, "Q2-TEXT")])
                )
        row: dict[str, Any] = {"profile": asdict(profile), "profile_id": profile.profile_id}
        for name, values in scores.items():
            row[name] = {
                "recall_at_k": mean(item.recall_at_k for item in values),
                "precision_at_k": mean(item.precision_at_k for item in values),
                "mrr": mean(item.mrr for item in values),
                "irrelevant_injection_rate": mean(item.irrelevant_memory_injection_rate for item in values),
                "duplicate_chunk_slot_rate": mean(item.duplicate_chunk_slot_rate for item in values),
                "superseded_retrieval_rate": mean(item.superseded_fact_retrieval_rate for item in values),
            }
        row["mean_query_estimated_tokens"] = mean(query_tokens)
        row["retrieval_latency_ms"] = aggregate(retrieval_latency_ms)
        rows.append(row)

    def rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
        hybrid = row["hybrid_event"]
        return (
            -hybrid["recall_at_k"],
            -hybrid["mrr"],
            hybrid["irrelevant_injection_rate"],
            hybrid["duplicate_chunk_slot_rate"],
            row["mean_query_estimated_tokens"],
            row["profile_id"],
        )

    selected_row = min(rows, key=rank)
    selected = next(profile for profile in profiles if profile.profile_id == selected_row["profile_id"])
    return selected, rows


async def _extract_semantic_facts(
    *,
    fixtures: Sequence[ConversationFixture],
    extractor: SemanticExtractor,
) -> tuple[dict[str, tuple[SemanticFact, ...]], list[dict[str, Any]]]:
    extracted: dict[str, tuple[SemanticFact, ...]] = {}
    score_rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        for event in fixture.events:
            facts = await extractor.extract(
                tenant_id=fixture.tenant_id,
                conversation_id=fixture.conversation_id,
                event=event,
            )
            extracted[event.event_id] = facts
            score = semantic_extraction_score(event, facts)
            score_rows.append({"event_id": event.event_id, **asdict(score), "precision": score.precision, "recall": score.recall, "f1": score.f1})
    return extracted, score_rows


def _select_confidence_threshold(
    fixtures: Sequence[ConversationFixture],
    extracted: Mapping[str, tuple[SemanticFact, ...]],
    candidates: Sequence[float],
) -> tuple[float, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for threshold in candidates:
        tp = fp = fn = prohibited = 0
        for fixture in fixtures:
            for event in fixture.events:
                facts = tuple(fact for fact in extracted[event.event_id] if fact.confidence >= threshold)
                score = semantic_extraction_score(event, facts)
                tp += score.true_positive
                fp += score.false_positive
                fn += score.false_negative
                prohibited += score.prohibited_extractions
        precision = None if tp + fp == 0 else tp / (tp + fp)
        recall = None if tp + fn == 0 else tp / (tp + fn)
        f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
        rows.append({"threshold": threshold, "true_positive": tp, "false_positive": fp, "false_negative": fn, "prohibited": prohibited, "precision": precision, "recall": recall, "f1": f1})
    eligible = [row for row in rows if row["prohibited"] == 0]
    if not eligible:
        raise DevelopmentInvalid("every semantic confidence candidate extracts prohibited data")
    selected = min(eligible, key=lambda row: (-(row["f1"] or 0), -(row["precision"] or 0), row["threshold"]))
    return float(selected["threshold"]), rows


def _select_fallback_policy(
    *,
    fixtures: Sequence[ConversationFixture],
    selected_profile: RetrievalProfile,
    retrieval: Mapping[str, Mapping[str, tuple[RankedChunk, ...]]],
    semantic_by_conversation: Mapping[str, tuple[SemanticFact, ...]],
    confidence_threshold: float,
    policies: Sequence[str],
) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for policy in policies:
        decisions: list[tuple[bool, bool]] = []
        for fixture in fixtures:
            for evaluation in fixture.evaluations:
                key = _key(fixture, evaluation)
                query, _ = fixture.query_and_reference(evaluation)
                data = retrieval[key]
                semantic = current_semantic_facts(
                    semantic_by_conversation[fixture.conversation_id],
                    tenant_id=fixture.tenant_id,
                    conversation_id=fixture.conversation_id,
                    before_event_sequence=fixture.event_by_id(evaluation.query_event_id).sequence,
                    confidence_threshold=confidence_threshold,
                )
                reasons = fallback_reasons(
                    policy=policy,
                    query=query.content,
                    dense=data["dense_event"],
                    lexical=data["bm25_event"],
                    semantic_facts=semantic,
                )
                decisions.append((bool(reasons), evaluation.fallback_required))
        rows.append({"policy": policy, **fallback_confusion(decisions)})

    def rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -(row["recall"] if row["recall"] is not None else -1),
            -(row["precision"] if row["precision"] is not None else -1),
            row["activation_rate"] if row["activation_rate"] is not None else 1,
            row["policy"],
        )

    selected = min(rows, key=rank)
    return str(selected["policy"]), rows


def _selected_retrieval(
    fixtures: Sequence[ConversationFixture],
    profile: RetrievalProfile,
    chunks: Mapping[tuple[str, str, str], tuple[MemoryChunk, ...]],
    queries: Mapping[tuple[str, str, str], str],
    vectors: Mapping[str, Sequence[float]],
) -> dict[str, dict[str, tuple[RankedChunk, ...]]]:
    result: dict[str, dict[str, tuple[RankedChunk, ...]]] = {}
    for fixture in fixtures:
        for evaluation in fixture.evaluations:
            events = _retrieve(fixture=fixture, evaluation=evaluation, profile=profile, chunks=chunks, queries=queries, vectors=vectors, unit="event")
            messages = _retrieve(fixture=fixture, evaluation=evaluation, profile=profile, chunks=chunks, queries=queries, vectors=vectors, unit="message")
            q1_messages = _retrieve(fixture=fixture, evaluation=evaluation, profile=profile, chunks=chunks, queries=queries, vectors=vectors, unit="message", variant="Q1")
            result[_key(fixture, evaluation)] = {
                "dense_event": events["dense"],
                "bm25_event": events["lexical"],
                "hybrid_event": events["hybrid"],
                "hybrid_message": messages["hybrid"],
                "r_dense_message": q1_messages["dense"],
            }
    return result


def _contexts(
    *,
    fixture: ConversationFixture,
    evaluation: EvaluationStep,
    profile: RetrievalProfile,
    retrieval: Mapping[str, tuple[RankedChunk, ...]],
    extracted_facts: Sequence[SemanticFact],
    curated: Sequence[SemanticFact],
    confidence_threshold: float,
    fallback_policy: str,
    manifest: Mapping[str, Any],
) -> dict[str, ComposedInput]:
    prefix = fixture.prefix_before(evaluation.query_event_id)
    current, _ = fixture.query_and_reference(evaluation)
    before = fixture.event_by_id(evaluation.query_event_id).sequence
    semantic = current_semantic_facts(
        extracted_facts,
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=before,
        confidence_threshold=confidence_threshold,
    )
    curated_current = current_semantic_facts(
        curated,
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=before,
        confidence_threshold=1.0,
    )
    reasons = fallback_reasons(
        policy=fallback_policy,
        query=current.content,
        dense=retrieval["dense_event"],
        lexical=retrieval["bm25_event"],
        semantic_facts=semantic,
    )
    total = int(manifest["budgets"]["total_input_tokens"])
    reserve = int(manifest["budgets"]["output_reserve_tokens"])
    fixed = retrieval["hybrid_event"]
    adaptive_episodic, adaptive_semantic = _adaptive_selection(
        prefix=prefix,
        current_user_content=current.content,
        active_event_count=profile.active_window_events,
        episodic=fixed,
        semantic=semantic,
        manifest=manifest,
    )
    common = {
        "prefix": prefix,
        "current_user": current,
        "active_event_count": profile.active_window_events,
        "total_input_tokens": total,
        "output_reserve_tokens": reserve,
    }
    return {
        "A": compose_input(arm="A", **common),
        "B": compose_input(arm="B", **common),
        "C": compose_input(arm="C", **common),
        "D-EVT": compose_input(arm="D-EVT", episodic=retrieval["dense_event"], **common),
        "E-EVT": compose_input(arm="E-EVT", episodic=retrieval["bm25_event"], **common),
        "F-MSG": compose_input(arm="F-MSG", episodic=retrieval["hybrid_message"], **common),
        "F-EVT": compose_input(arm="F-EVT", episodic=fixed, **common),
        "G-SEM": compose_input(arm="G-SEM", episodic=fixed, semantic=semantic, **common),
        "G-ADAPT": compose_input(arm="G-ADAPT", episodic=adaptive_episodic, semantic=adaptive_semantic, **common),
        "G-FALLBACK": compose_input(arm="G-FALLBACK", episodic=adaptive_episodic, semantic=adaptive_semantic, fallback=bool(reasons), fallback_reason_codes=reasons, **common),
        "R": compose_input(arm="R", episodic=retrieval["r_dense_message"], semantic=curated_current, **common),
    }


def _adaptive_selection(
    *,
    prefix: Sequence[Any],
    current_user_content: str,
    active_event_count: int,
    episodic: Sequence[RankedChunk],
    semantic: Sequence[SemanticFact],
    manifest: Mapping[str, Any],
) -> tuple[tuple[RankedChunk, ...], tuple[SemanticFact, ...]]:
    total = int(manifest["budgets"]["total_input_tokens"])
    reserve = int(manifest["budgets"]["output_reserve_tokens"])
    system = int(manifest["budgets"]["system_tokens"])
    active = tuple(prefix[-active_event_count:])
    headroom = max(
        0,
        total
        - reserve
        - system
        - estimated_tokens(current_user_content)
        - sum(estimated_tokens(event.text) for event in active),
    )
    tiers = sorted(
        manifest["adaptive_fallback"]["injection_tiers"],
        key=lambda item: -int(item["minimum_headroom_tokens"]),
    )
    tier = next(item for item in tiers if headroom >= int(item["minimum_headroom_tokens"]))
    memory_budget = min(headroom, 1024)
    semantic_budget = int(memory_budget * float(tier["semantic_fraction"]))
    episodic_budget = memory_budget - semantic_budget

    selected_semantic: list[SemanticFact] = []
    used = 0
    for fact in sorted(semantic, key=lambda item: (-item.effective_sequence, item.fact_key)):
        cost = estimated_tokens(f"{fact.fact_key}:{fact.value}")
        if used + cost <= semantic_budget:
            selected_semantic.append(fact)
            used += cost
    selected_episodic: list[RankedChunk] = []
    used = 0
    for item in episodic:
        cost = estimated_tokens(item.chunk.text)
        if used + cost <= episodic_budget:
            selected_episodic.append(item)
            used += cost
    return tuple(selected_episodic), tuple(selected_semantic)


async def _generate_all(
    *,
    fixtures: Sequence[ConversationFixture],
    contexts: Mapping[str, Mapping[str, ComposedInput]],
    api_key: str,
    manifest: Mapping[str, Any],
    ledger: ExternalCallLedger,
) -> list[dict[str, Any]]:
    model = str(manifest["generation"]["model"])
    provider = DevelopmentOpenAIProvider(
        OpenAIProviderConfig(
            api_key=api_key,
            model=model,
            timeout_s=float(manifest["execution"]["external_timeout_seconds"]),
            max_attempts=1,
            backoff_base_ms=0,
            backoff_max_ms=0,
        ),
        max_output_tokens=int(manifest["generation"]["max_output_tokens"]),
    )
    jobs: list[tuple[ConversationFixture, EvaluationStep, str, ComposedInput]] = []
    for fixture in fixtures:
        for evaluation in fixture.evaluations:
            step_contexts = contexts[_key(fixture, evaluation)]
            for arm in ARMS:
                jobs.append((fixture, evaluation, arm, step_contexts[arm]))
    expected = len(fixtures) * 4 * len(ARMS)
    if len(jobs) != expected or expected != int(manifest["external_call_limits"]["generation"]):
        raise DevelopmentInvalid("generation schedule differs from approved 528 calls")

    results: list[dict[str, Any]] = []
    lock = asyncio.Lock()
    queue: asyncio.Queue[tuple[ConversationFixture, EvaluationStep, str, ComposedInput]] = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)
    failure: BaseException | None = None

    async def worker() -> None:
        nonlocal failure
        while failure is None:
            try:
                fixture, evaluation, arm, context = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                generated = await generate_streamed(
                    provider=provider,
                    messages=context.messages,
                    ledger=ledger,
                    model=model,
                    step_id=evaluation.step_id,
                    arm=arm,
                )
                score = answer_score(generated.content, evaluation.expected)
                prefix = fixture.prefix_before(evaluation.query_event_id)
                echo = echo_overlap(
                    generated.content,
                    [message.content for event in prefix for message in event.messages if message.role == "assistant"],
                    [message.content for message in context.messages if message.role == "system"][1:],
                )
                row = {
                    "conversation_id": fixture.conversation_id,
                    "tenant_id": fixture.tenant_id,
                    "step_id": evaluation.step_id,
                    "arm": arm,
                    "answer": generated.content,
                    "input_tokens": generated.input_tokens,
                    "output_tokens": generated.output_tokens,
                    "total_tokens": generated.total_tokens,
                    "latency_ms": generated.latency_ms,
                    "ttft_ms": generated.ttft_ms,
                    "model": generated.model,
                    "recall": score.conversational_recall_accuracy,
                    "consistency": score.fact_consistency,
                    "echo_overlap": echo,
                    "estimated_input_tokens": context.estimated_input_tokens,
                    "component_tokens": dict(context.component_tokens),
                    "active_event_ids": list(context.active_event_ids),
                    "episodic_event_ids": list(context.episodic_event_ids),
                    "episodic_chunk_ids": list(context.episodic_chunk_ids),
                    "semantic_fact_ids": list(context.semantic_fact_ids),
                    "fallback_used": context.fallback_used,
                    "fallback_reasons": list(context.fallback_reasons),
                    "slices": list(evaluation.slices),
                }
                async with lock:
                    results.append(row)
            except BaseException as exc:
                failure = exc
            finally:
                queue.task_done()

    workers = [
        asyncio.create_task(worker())
        for _ in range(int(manifest["execution"]["generation_concurrency"]))
    ]
    await asyncio.gather(*workers)
    if failure is not None:
        raise DevelopmentInvalid(f"generation execution failed: {type(failure).__name__}") from failure
    if len(results) != expected:
        raise DevelopmentInvalid("generation result count is incomplete")
    results.sort(key=lambda row: (row["conversation_id"], row["step_id"], ARMS.index(row["arm"])))
    return results


def _summarize(
    *,
    fixtures: Sequence[ConversationFixture],
    generation: Sequence[Mapping[str, Any]],
    retrieval: Mapping[str, Mapping[str, tuple[RankedChunk, ...]]],
    chunks: Mapping[tuple[str, str, str], tuple[MemoryChunk, ...]],
    queries: Mapping[tuple[str, str, str], str],
    profile: RetrievalProfile,
    semantic_scores: Sequence[Mapping[str, Any]],
    confidence_threshold: float,
    confidence_rows: Sequence[Mapping[str, Any]],
    fallback_policy: str,
    fallback_rows: Sequence[Mapping[str, Any]],
    profile_rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    ledger_summary: Mapping[str, Any],
) -> dict[str, Any]:
    by_arm: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in generation:
        by_arm[str(row["arm"])].append(row)
    quality: dict[str, Any] = {}
    for arm in ARMS:
        items = by_arm[arm]
        by_conversation: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in items:
            by_conversation[str(item["conversation_id"])].append(item)
        recall = [mean(float(value["recall"]) for value in values) for values in by_conversation.values()]
        consistency = [mean(float(value["consistency"]) for value in values) for values in by_conversation.values()]
        quality[arm] = {
            "conversational_recall_accuracy": mean(recall),
            "fact_consistency": mean(consistency),
            "input_tokens_actual": sum(int(item["input_tokens"] or 0) for item in items),
            "output_tokens_actual": sum(int(item["output_tokens"] or 0) for item in items),
            "input_tokens_estimated": sum(int(item["estimated_input_tokens"]) for item in items),
            "latency_ms": aggregate([float(item["latency_ms"]) for item in items]),
            "ttft_ms": aggregate([float(item["ttft_ms"]) for item in items if item["ttft_ms"] is not None]),
            "echo_overlap": aggregate([float(item["echo_overlap"]) for item in items]),
            "fallback_rate": mean(float(bool(item["fallback_used"])) for item in items),
            "usage_complete": all(item["input_tokens"] is not None and item["output_tokens"] is not None for item in items),
        }

    slice_names = sorted({slice_name for fixture in fixtures for evaluation in fixture.evaluations for slice_name in evaluation.slices})
    slices: dict[str, Any] = {}
    for slice_name in slice_names:
        slices[slice_name] = {}
        for arm in ARMS:
            items = [row for row in by_arm[arm] if slice_name in row["slices"]]
            slices[slice_name][arm] = {
                "steps": len(items),
                "recall": mean(float(item["recall"]) for item in items) if items else None,
                "consistency": mean(float(item["consistency"]) for item in items) if items else None,
            }

    retrieval_summary: dict[str, Any] = {}
    arm_keys = {
        "D-EVT": "dense_event",
        "E-EVT": "bm25_event",
        "F-MSG": "hybrid_message",
        "F-EVT": "hybrid_event",
        "R": "r_dense_message",
    }
    for arm, key_name in arm_keys.items():
        scores = []
        role_scores: dict[str, list[Mapping[str, Any]]] = {"user": [], "assistant": []}
        for fixture in fixtures:
            events_by_id = {event.event_id: event for event in fixture.events}
            for evaluation in fixture.evaluations:
                results = retrieval[_key(fixture, evaluation)][key_name]
                scores.append(retrieval_score(results, evaluation=evaluation, evaluation_top_k_events=profile.top_k))
                for role in role_scores:
                    role_scores[role].append(role_retrieval_score(results, evaluation=evaluation, role=role, events_by_id=events_by_id, evaluation_top_k_events=profile.top_k))
        retrieval_summary[arm] = {
            "precision_at_k": mean(item.precision_at_k for item in scores),
            "recall_at_k": mean(item.recall_at_k for item in scores),
            "mrr": mean(item.mrr for item in scores),
            "irrelevant_injection_rate": mean(item.irrelevant_memory_injection_rate for item in scores),
            "duplicate_chunk_slot_rate": mean(item.duplicate_chunk_slot_rate for item in scores),
            "superseded_retrieval_rate": mean(item.superseded_fact_retrieval_rate for item in scores),
            "by_source_role": {
                role: {
                    field: mean(float(row[field]) for row in values if row[field] is not None)
                    if any(row[field] is not None for row in values)
                    else None
                    for field in ("precision_at_k", "recall_at_k", "mrr")
                }
                for role, values in role_scores.items()
            },
        }
    semantic_totals = {
        field: sum(int(row[field]) for row in semantic_scores)
        for field in ("true_positive", "false_positive", "false_negative", "prohibited_extractions", "provenance_complete", "extracted_count")
    }
    prices = manifest["pricing"]
    costs: dict[str, Any] = {}
    ledger_path = PACKAGE / "runs" / "development-external-calls.jsonl"
    semantic_usage = _ledger_kind_usage(ledger_path, "semantic_extraction")
    event_index_tokens = sum(
        estimated_tokens(chunk.text)
        for fixture in fixtures
        for chunk in chunks[(fixture.conversation_id, profile.profile_id, "event")]
    )
    message_index_tokens = sum(
        estimated_tokens(chunk.text)
        for fixture in fixtures
        for chunk in chunks[(fixture.conversation_id, profile.profile_id, "message")]
    )
    q2_tokens = sum(
        estimated_tokens(queries[(evaluation.step_id, profile.profile_id, "Q2-TEXT")])
        for fixture in fixtures
        for evaluation in fixture.evaluations
    )
    q1_tokens = sum(
        estimated_tokens(queries[(evaluation.step_id, profile.profile_id, "Q1")])
        for fixture in fixtures
        for evaluation in fixture.evaluations
    )
    logical_embedding_tokens = {
        "A": 0,
        "B": 0,
        "C": 0,
        "D-EVT": event_index_tokens + q2_tokens,
        "E-EVT": 0,
        "F-MSG": message_index_tokens + q2_tokens,
        "F-EVT": event_index_tokens + q2_tokens,
        "G-SEM": event_index_tokens + q2_tokens,
        "G-ADAPT": event_index_tokens + q2_tokens,
        "G-FALLBACK": event_index_tokens + q2_tokens,
        "R": message_index_tokens + q1_tokens,
    }
    for arm in ARMS:
        generation_input = quality[arm]["input_tokens_actual"]
        generation_output = quality[arm]["output_tokens_actual"]
        generation_cost = None
        if quality[arm]["usage_complete"]:
            generation_cost = (generation_input * float(prices["generation_input_per_million"]) + generation_output * float(prices["generation_output_per_million"])) / 1_000_000
        embedding_tokens = logical_embedding_tokens[arm]
        embedding_cost = embedding_tokens * float(prices["embedding_input_per_million"]) / 1_000_000
        semantic_cost: float | None = 0.0
        if arm in {"G-SEM", "G-ADAPT", "G-FALLBACK"}:
            semantic_cost = _generation_cost(semantic_usage, prices)
        total_cost = (
            None
            if generation_cost is None or semantic_cost is None
            else generation_cost + embedding_cost + semantic_cost
        )
        correct_recall = sum(float(item["recall"]) for item in by_arm[arm])
        cost_per_recall: float | None = None
        cost_per_recall_reason: str | None = None
        if total_cost is None:
            cost_per_recall_reason = "required_cost_unavailable"
        elif correct_recall == 0:
            cost_per_recall_reason = "undefined_zero_correct_recall"
        else:
            cost_per_recall = total_cost / correct_recall
        costs[arm] = {
            "generation_api_cost": generation_cost,
            "logical_embedding_tokens_estimated": embedding_tokens,
            "embedding_api_cost_estimated": embedding_cost,
            "semantic_extraction_cost": semantic_cost,
            "total_estimated_api_cost": total_cost,
            "api_cost_per_correct_recall": cost_per_recall,
            "api_cost_per_correct_recall_reason": cost_per_recall_reason,
        }

    selected_profile_row = next(
        row for row in profile_rows if row["profile_id"] == profile.profile_id
    )
    dimensions = int(manifest["dense"]["dimensions"])
    event_chunks = [
        chunk
        for fixture in fixtures
        for chunk in chunks[(fixture.conversation_id, profile.profile_id, "event")]
    ]
    message_chunks = [
        chunk
        for fixture in fixtures
        for chunk in chunks[(fixture.conversation_id, profile.profile_id, "message")]
    ]
    storage_growth = {
        "event_index": _storage_estimate(event_chunks, dimensions=dimensions),
        "message_index": _storage_estimate(message_chunks, dimensions=dimensions),
        "note": "Vector bytes are float32 payload estimates and exclude database/index overhead.",
    }
    observed_generation = _ledger_kind_usage(ledger_path, "generation")
    observed_embedding = _ledger_kind_usage(ledger_path, "embedding_batch")
    observed_semantic = semantic_usage
    observed_generation_cost = _generation_cost(observed_generation, prices)
    observed_semantic_cost = _generation_cost(observed_semantic, prices)
    observed_embedding_cost = (
        int(observed_embedding["estimated_tokens"])
        * float(prices["embedding_input_per_million"])
        / 1_000_000
    )
    observed_total = (
        None
        if observed_generation_cost is None or observed_semantic_cost is None
        else observed_generation_cost + observed_semantic_cost + observed_embedding_cost
    )
    observed_external_cost = {
        "generation_api_cost": observed_generation_cost,
        "semantic_extraction_api_cost": observed_semantic_cost,
        "embedding_api_cost_estimated": observed_embedding_cost,
        "total_estimated_api_cost": observed_total,
        "usage_complete": {
            "generation": observed_generation["usage_complete"],
            "semantic_extraction": observed_semantic["usage_complete"],
            "embedding": "tokenizer_estimate_only",
        },
    }
    chronological_costs = _chronological_logical_costs(
        fixtures=fixtures,
        by_arm=by_arm,
        chunks=chunks,
        queries=queries,
        profile=profile,
        manifest=manifest,
        semantic_usage_by_event=_ledger_usage_by_step(
            ledger_path, "semantic_extraction"
        ),
    )

    def comparator_rank(arm: str) -> tuple[Any, ...]:
        cost = costs[arm]["total_estimated_api_cost"]
        return (
            -quality[arm]["conversational_recall_accuracy"],
            -quality[arm]["fact_consistency"],
            retrieval_summary[arm]["irrelevant_injection_rate"],
            float("inf") if cost is None else cost,
            ("D-EVT", "E-EVT", "F-EVT").index(arm),
        )

    s_star = min(("D-EVT", "E-EVT"), key=comparator_rank)
    e_star = min(("D-EVT", "E-EVT", "F-EVT"), key=comparator_rank)
    fallback_observations = []
    evaluation_by_step = {evaluation.step_id: evaluation for fixture in fixtures for evaluation in fixture.evaluations}
    for row in by_arm["G-FALLBACK"]:
        fallback_observations.append((bool(row["fallback_used"]), evaluation_by_step[str(row["step_id"])].fallback_required))
    semantic_precision_denominator = semantic_totals["true_positive"] + semantic_totals["false_positive"]
    semantic_recall_denominator = semantic_totals["true_positive"] + semantic_totals["false_negative"]
    semantic_precision = None if semantic_precision_denominator == 0 else semantic_totals["true_positive"] / semantic_precision_denominator
    semantic_recall = None if semantic_recall_denominator == 0 else semantic_totals["true_positive"] / semantic_recall_denominator
    semantic_f1 = None if semantic_precision is None or semantic_recall is None or semantic_precision + semantic_recall == 0 else 2 * semantic_precision * semantic_recall / (semantic_precision + semantic_recall)
    return {
        "quality": quality,
        "slices": slices,
        "retrieval": retrieval_summary,
        "selected_s_star": s_star,
        "selected_e_star": e_star,
        "semantic_extraction": {**semantic_totals, "precision": semantic_precision, "recall": semantic_recall, "f1": semantic_f1, "confidence_threshold": confidence_threshold, "candidate_rows": list(confidence_rows)},
        "fallback": {"selected_policy": fallback_policy, "candidate_rows": list(fallback_rows), "observed": fallback_confusion(fallback_observations)},
        "selected_retrieval_profile": asdict(profile),
        "retrieval_profile_candidates": list(profile_rows),
        "retrieval_runtime": {
            "selected_profile_calibration_latency_ms": selected_profile_row[
                "retrieval_latency_ms"
            ],
            "scope": "in-process exact dense, BM25, and fusion over development fixtures",
        },
        "storage_and_index_growth": storage_growth,
        "logical_costs": costs,
        "chronological_logical_costs": chronological_costs,
        "observed_external_cost": observed_external_cost,
        "observed_external_execution": dict(ledger_summary),
    }


def _ledger_kind_usage(path: Path, kind: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "calls": 0,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_tokens": 0,
            "usage_complete": False,
        }
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    successes = [row for row in rows if row.get("kind") == kind and row.get("event") == "succeeded"]
    usage_complete = bool(successes) and all(
        row.get("input_tokens") is not None and row.get("output_tokens") is not None
        for row in successes
    )
    return {
        "calls": len(successes),
        "input_tokens": (
            sum(int(row["input_tokens"]) for row in successes)
            if usage_complete
            else None
        ),
        "output_tokens": (
            sum(int(row["output_tokens"]) for row in successes)
            if usage_complete
            else None
        ),
        "estimated_tokens": sum(
            int(row.get("estimated_tokens") or 0) for row in successes
        ),
        "usage_complete": usage_complete,
    }


def _ledger_usage_by_step(path: Path, kind: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("kind") != kind or row.get("event") != "succeeded":
            continue
        step_id = str(row.get("step_id"))
        if step_id in result:
            raise DevelopmentInvalid(f"duplicate {kind} usage for step {step_id}")
        result[step_id] = {
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "usage_complete": (
                row.get("input_tokens") is not None
                and row.get("output_tokens") is not None
            ),
        }
    return result


def _generation_cost(usage: Mapping[str, Any], prices: Mapping[str, Any]) -> float | None:
    if not usage.get("usage_complete"):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    return (
        int(input_tokens) * float(prices["generation_input_per_million"])
        + int(output_tokens) * float(prices["generation_output_per_million"])
    ) / 1_000_000


def _storage_estimate(
    chunks: Sequence[MemoryChunk],
    *,
    dimensions: int,
) -> dict[str, int]:
    return {
        "artifact_count": len(chunks),
        "unique_source_events": len({chunk.source_event_id for chunk in chunks}),
        "unique_source_messages": len(
            {message_id for chunk in chunks for message_id in chunk.source_message_ids}
        ),
        "stored_text_bytes": sum(len(chunk.text.encode("utf-8")) for chunk in chunks),
        "vector_payload_bytes_estimated": len(chunks) * dimensions * 4,
    }


def _chronological_logical_costs(
    *,
    fixtures: Sequence[ConversationFixture],
    by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
    chunks: Mapping[tuple[str, str, str], tuple[MemoryChunk, ...]],
    queries: Mapping[tuple[str, str, str], str],
    profile: RetrievalProfile,
    manifest: Mapping[str, Any],
    semantic_usage_by_event: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    prices = manifest["pricing"]
    embedding_rate = float(prices["embedding_input_per_million"]) / 1_000_000
    generation_by_key = {
        (str(row["conversation_id"]), str(row["step_id"]), str(row["arm"])): row
        for arm in ARMS
        for row in by_arm[arm]
    }
    positions: dict[int, dict[str, list[float | None]]] = {
        index: {arm: [] for arm in ARMS} for index in range(1, 5)
    }
    for fixture in fixtures:
        evaluations = sorted(
            fixture.evaluations,
            key=lambda item: fixture.event_by_id(item.query_event_id).sequence,
        )
        event_chunks = chunks[(fixture.conversation_id, profile.profile_id, "event")]
        message_chunks = chunks[(fixture.conversation_id, profile.profile_id, "message")]
        cumulative_generation: dict[str, float | None] = {arm: 0.0 for arm in ARMS}
        for position, evaluation in enumerate(evaluations, start=1):
            sequence = fixture.event_by_id(evaluation.query_event_id).sequence
            event_index_tokens = sum(
                estimated_tokens(chunk.text)
                for chunk in event_chunks
                if chunk.source_event_sequence <= sequence
            )
            message_index_tokens = sum(
                estimated_tokens(chunk.text)
                for chunk in message_chunks
                if chunk.source_event_sequence <= sequence
            )
            q2_tokens = sum(
                estimated_tokens(queries[(item.step_id, profile.profile_id, "Q2-TEXT")])
                for item in evaluations[:position]
            )
            q1_tokens = sum(
                estimated_tokens(queries[(item.step_id, profile.profile_id, "Q1")])
                for item in evaluations[:position]
            )
            semantic_cost: float | None = 0.0
            for event in fixture.events:
                if event.sequence > sequence:
                    continue
                usage = semantic_usage_by_event.get(event.event_id)
                if usage is None:
                    semantic_cost = None
                    break
                item_cost = _generation_cost(usage, prices)
                if item_cost is None:
                    semantic_cost = None
                    break
                semantic_cost += item_cost
            for arm in ARMS:
                row = generation_by_key[
                    (fixture.conversation_id, evaluation.step_id, arm)
                ]
                if cumulative_generation[arm] is not None:
                    if row["input_tokens"] is None or row["output_tokens"] is None:
                        cumulative_generation[arm] = None
                    else:
                        cumulative_generation[arm] += (
                            int(row["input_tokens"])
                            * float(prices["generation_input_per_million"])
                            + int(row["output_tokens"])
                            * float(prices["generation_output_per_million"])
                        ) / 1_000_000
                index_and_query_tokens = 0
                if arm in {"D-EVT", "F-EVT", "G-SEM", "G-ADAPT", "G-FALLBACK"}:
                    index_and_query_tokens = event_index_tokens + q2_tokens
                elif arm == "F-MSG":
                    index_and_query_tokens = message_index_tokens + q2_tokens
                elif arm == "R":
                    index_and_query_tokens = message_index_tokens + q1_tokens
                memory_cost = index_and_query_tokens * embedding_rate
                arm_semantic_cost: float | None = (
                    semantic_cost
                    if arm in {"G-SEM", "G-ADAPT", "G-FALLBACK"}
                    else 0.0
                )
                generation_cost = cumulative_generation[arm]
                total = (
                    None
                    if generation_cost is None or arm_semantic_cost is None
                    else generation_cost + memory_cost + arm_semantic_cost
                )
                positions[position][arm].append(total)

    aggregated: dict[str, dict[str, float | int | None]] = {}
    for position, arms in positions.items():
        aggregated[str(position)] = {
            arm: (
                None
                if any(value is None for value in values)
                else sum(float(value) for value in values if value is not None)
            )
            for arm, values in arms.items()
        }
        aggregated[str(position)]["reference_event_sequence"] = (4, 8, 10, 12)[
            position - 1
        ]

    break_even: dict[str, int | None] = {}
    for arm in ARMS:
        candidate: int | None = None
        for position in range(1, 5):
            suffix = range(position, 5)
            if all(
                aggregated[str(index)][arm] is not None
                and aggregated[str(index)]["B"] is not None
                and float(aggregated[str(index)][arm])
                <= float(aggregated[str(index)]["B"])
                for index in suffix
            ):
                candidate = position
                break
        break_even[arm] = candidate
    return {
        "unit": "aggregate cumulative USD across development conversations by evaluated response position",
        "index_charge_rule": "Each source event is charged once when it becomes eligible; query and generation are charged per evaluated request. Physical sharing is ignored for per-arm attribution.",
        "positions": aggregated,
        "break_even_evaluated_response_position_vs_B": break_even,
    }


def _render_report(analysis: Mapping[str, Any]) -> str:
    lines = [
        "# ORQ-29 Gate 1 development calibration report",
        "",
        "**Status:** DEVELOPMENT_ONLY — no held-out generated or accessed",
        "",
        f"- Run ID: `{analysis['run_id']}`",
        f"- Manifest SHA-256: `{analysis['development_manifest_sha256']}`",
        f"- Development dataset SHA-256: `{analysis['development_dataset_sha256']}`",
        f"- Origin commit verified: `{analysis['origin_attestation']['expected_commit']}`",
        f"- Selected retrieval profile: `{analysis['summary']['selected_retrieval_profile']['profile_id']}`",
        f"- Selected S*: `{analysis['summary']['selected_s_star']}`",
        f"- Selected E*: `{analysis['summary']['selected_e_star']}`",
        f"- Selected semantic confidence: `{analysis['summary']['semantic_extraction']['confidence_threshold']}`",
        f"- Selected fallback policy: `{analysis['summary']['fallback']['selected_policy']}`",
        "",
        "## Development quality",
        "",
        "| Arm | Recall | Consistency | Input tokens | p95 TTFT ms | Estimated API cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        quality = analysis["summary"]["quality"][arm]
        cost = analysis["summary"]["logical_costs"][arm]
        total_cost = cost["total_estimated_api_cost"]
        cost_text = "null" if total_cost is None else f"{total_cost:.8f}"
        lines.append(
            f"| {arm} | {quality['conversational_recall_accuracy']:.4f} | "
            f"{quality['fact_consistency']:.4f} | {quality['input_tokens_actual']} | "
            f"{quality['ttft_ms']['p95'] or 0:.2f} | {cost_text} |"
        )
    calls = analysis["summary"]["observed_external_execution"]["counts"]
    lines.extend(
        [
            "",
            "## External call ledger",
            "",
            f"- Generation calls: `{calls['generation']} / 528`",
            f"- Semantic extraction calls: `{calls['semantic_extraction']} / 144`",
            f"- Grouped embedding calls: `{calls['embedding_batch']} / 120`",
            f"- Total external calls: `{calls['total']} / 792`",
            "",
            "## Boundary",
            "",
            "This is unblinded development calibration, not a final pre-registration and not a "
            "Gate 1 hypothesis verdict. The new held-out seed, path, hash, and bundle remain null. "
            "No Gate 2, Gate 3, or production work is authorized.",
            "",
        ]
    )
    return "\n".join(lines)


async def run_external(*, manifest_path: Path) -> Path:
    manifest = load_manifest(manifest_path)
    dataset_manifest_path = DATA / "dataset-manifest.json"
    dataset_manifest = verify_dataset_manifest(dataset_manifest_path, development_manifest_sha256=manifest.sha256)
    fixtures = load_dataset(DATA / dataset_manifest["development"]["path"], expected_split="development")
    api_key = settings.openai_api_key
    if not api_key:
        raise DevelopmentInvalid("OPENAI_API_KEY is not configured")
    reservation = RUNS / "development-external.reserved"
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    try:
        with reservation.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"run_id": run_id, "manifest_sha256": manifest.sha256, "status": "started"}, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise DevelopmentInvalid("the single authorized development execution is already reserved") from exc

    origin = verify_origin(manifest)
    registration = {
        "schema_version": "orq29-development-registration-v1",
        "status": "frozen_before_external_calls",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_manifest_sha256": manifest.sha256,
        "dataset_manifest_sha256": sha256_file(dataset_manifest_path),
        "development_dataset_sha256": sha256_file(DATA / dataset_manifest["development"]["path"]),
        "heldout": {"seed": None, "path": None, "hash": None, "bundle": None},
        "origin_attestation": origin,
        "instrument_hashes": instrument_hashes([PACKAGE / path for path in INSTRUMENT_FILES]),
    }
    registration_path = PACKAGE / "development-registration.json"
    registration_path.write_text(json.dumps(registration, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ledger_path = RUNS / "development-external-calls.jsonl"
    ledger = ExternalCallLedger(ledger_path, run_id=run_id, manifest=manifest, origin_attestation=origin)
    started_at = time.monotonic()
    state_path = PACKAGE / "development-state.json"
    try:
        profiles = generate_profiles(manifest.payload)
        chunks, queries, embedding_texts = _profile_assets(fixtures, profiles)
        vectors = await _embed_all(texts=embedding_texts, api_key=api_key, manifest=manifest.payload, ledger=ledger)
        selected_profile, profile_rows = _calibrate_profiles(fixtures=fixtures, profiles=profiles, chunks=chunks, queries=queries, vectors=vectors)
        retrieval = _selected_retrieval(fixtures, selected_profile, chunks, queries, vectors)
        extractor = SemanticExtractor(
            api_key=api_key,
            model=manifest.payload["semantic"]["model"],
            prompt_version=manifest.payload["semantic"]["prompt_version"],
            ledger=ledger,
            timeout_s=float(
                manifest.payload["execution"]["external_timeout_seconds"]
            ),
        )
        extracted_by_event, semantic_scores = await _extract_semantic_facts(fixtures=fixtures, extractor=extractor)
        confidence, confidence_rows = _select_confidence_threshold(fixtures, extracted_by_event, manifest.payload["semantic"]["confidence_thresholds"])
        semantic_by_conversation = {
            fixture.conversation_id: tuple(fact for event in fixture.events for fact in extracted_by_event[event.event_id])
            for fixture in fixtures
        }
        fallback_policy, fallback_rows = _select_fallback_policy(fixtures=fixtures, selected_profile=selected_profile, retrieval=retrieval, semantic_by_conversation=semantic_by_conversation, confidence_threshold=confidence, policies=manifest.payload["adaptive_fallback"]["fallback_policies"])
        context_rows: dict[str, dict[str, ComposedInput]] = {}
        for fixture in fixtures:
            extracted = semantic_by_conversation[fixture.conversation_id]
            curated = curated_facts(tenant_id=fixture.tenant_id, conversation_id=fixture.conversation_id, events=fixture.events)
            for evaluation in fixture.evaluations:
                key = _key(fixture, evaluation)
                context_rows[key] = _contexts(fixture=fixture, evaluation=evaluation, profile=selected_profile, retrieval=retrieval[key], extracted_facts=extracted, curated=curated, confidence_threshold=confidence, fallback_policy=fallback_policy, manifest=manifest.payload)
        generation = await _generate_all(fixtures=fixtures, contexts=context_rows, api_key=api_key, manifest=manifest.payload, ledger=ledger)
        ledger_summary = ledger.summary()
        if ledger_summary["unknown_outcome"] or ledger_summary["failed"]:
            raise DevelopmentInvalid("external-call trace contains failed or unknown outcomes")
        limits = manifest.call_limits
        if any(ledger_summary["counts"][kind] > int(limits[kind]) for kind in ("generation", "semantic_extraction", "embedding_batch", "total")):
            raise DevelopmentInvalid("an approved external-call limit was exceeded")
        summary = _summarize(fixtures=fixtures, generation=generation, retrieval=retrieval, chunks=chunks, queries=queries, profile=selected_profile, semantic_scores=semantic_scores, confidence_threshold=confidence, confidence_rows=confidence_rows, fallback_policy=fallback_policy, fallback_rows=fallback_rows, profile_rows=profile_rows, manifest=manifest.payload, ledger_summary=ledger_summary)
        payload = {
            "schema_version": "orq29-development-run-v1",
            "status": "DEVELOPMENT_COMPLETE_NOT_PREREGISTERED",
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started_at,
            "development_manifest_sha256": manifest.sha256,
            "development_registration_sha256": sha256_file(registration_path),
            "dataset_manifest_sha256": sha256_file(dataset_manifest_path),
            "development_dataset_sha256": sha256_file(DATA / dataset_manifest["development"]["path"]),
            "origin_attestation": origin,
            "heldout": {"seed": None, "path": None, "hash": None, "bundle": None, "accessed": False},
            "summary": summary,
            "generation_observations": generation,
        }
        output = RUNS / f"development-{run_id}.json"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (PACKAGE / "development-analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (PACKAGE / "development-report.md").write_text(_render_report(payload), encoding="utf-8")
        state_path.write_text(json.dumps({"status": "DEVELOPMENT_COMPLETE_NOT_PREREGISTERED", "run_id": run_id, "run_sha256": sha256_file(output), "heldout_accessed": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
    except BaseException as exc:
        state_path.write_text(json.dumps({"status": "DEVELOPMENT_INVALID", "run_id": run_id, "reason": type(exc).__name__, "heldout_accessed": False, "external_call_summary": ledger.summary()}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise


def validate_only(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    dataset_manifest_path = DATA / "dataset-manifest.json"
    dataset = verify_dataset_manifest(dataset_manifest_path, development_manifest_sha256=manifest.sha256)
    fixtures = load_dataset(DATA / dataset["development"]["path"], expected_split="development")
    profiles = generate_profiles(manifest.payload)
    return {
        "status": "VALIDATED_WITHOUT_EXTERNAL_CALLS",
        "manifest_sha256": manifest.sha256,
        "development_dataset_sha256": sha256_file(DATA / dataset["development"]["path"]),
        "conversations": len(fixtures),
        "evaluation_steps": sum(len(fixture.evaluations) for fixture in fixtures),
        "candidate_profiles": len(profiles),
        "heldout": manifest.payload["heldout"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ORQ-29 authoring/development calibration only.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--execute-external", action="store_true")
    args = parser.parse_args()
    if not args.execute_external:
        print(json.dumps(validate_only(args.manifest.resolve()), indent=2, sort_keys=True))
        return 0
    output = asyncio.run(run_external(manifest_path=args.manifest.resolve()))
    print(f"development_run={output}")
    print(f"development_run_sha256={sha256_file(output)}")
    print("heldout_accessed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
