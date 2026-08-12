from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.types import ChatMessage
from app.core.providers.openai_provider import OpenAIProviderConfig
from uuid import uuid4

from experiments.conversational_memory.costs import (
    PriceTable,
    api_cost_per_correct_recall,
    embedding_cost,
    generation_cost,
    nullable_sum,
)
from experiments.conversational_memory.analyze_development import paired_bootstrap_interval
from experiments.conversational_memory.memory import MemoryChunk, RetrievedChunk
from experiments.conversational_memory.metrics import answer_metrics, ranking_metrics
from experiments.conversational_memory.run_experiment import (
    GuardFailure,
    compute_break_even,
    load_registration,
    select_candidate,
)
from experiments.conversational_memory.execution import ExecutionLedger, summarize_execution_ledger
from experiments.conversational_memory.providers import ConversationExperimentOpenAIProvider


REGISTRATION = Path("experiments/conversational_memory/registration.json")


def _result(source: str, sequence: int, ordinal: int = 0) -> RetrievedChunk:
    chunk = MemoryChunk(
        artifact_id=f"a-{source}-{ordinal}",
        tenant_id="tenant",
        conversation_id="conversation",
        source_message_id=source,
        source_role="user" if sequence % 2 else "assistant",
        source_sequence=sequence,
        chunk_ordinal=ordinal,
        start_offset=0,
        end_offset=1,
        content=source,
        source_hash="s",
        embedding_input_hash="e",
        index_version="v1",
    )
    return RetrievedChunk(chunk, 1.0)


def test_message_level_metrics_do_not_backfill_duplicate_chunk_slots() -> None:
    results = (_result("gold-a", 1, 0), _result("gold-a", 1, 1), _result("gold-b", 2))
    metric = ranking_metrics(
        results,
        gold_source_message_ids=("gold-a", "gold-b"),
        superseded_source_message_ids=(),
        evaluation_top_k_messages=2,
    )
    assert metric.precision_at_k == 1.0
    assert metric.recall_at_k == 1.0
    assert metric.duplicate_chunk_slot_rate == pytest.approx(1 / 3)
    assert metric.delivered_chunk_count == 3
    assert metric.unique_source_count == 2


def test_unfilled_unique_message_positions_are_not_free_precision() -> None:
    metric = ranking_metrics(
        (_result("gold-a", 1, 0), _result("gold-a", 1, 1)),
        gold_source_message_ids=("gold-a", "gold-b"),
        superseded_source_message_ids=(),
        evaluation_top_k_messages=2,
    )
    assert metric.precision_at_k == 0.5
    assert metric.recall_at_k == 0.5


def test_superseded_and_irrelevant_injection_are_observable() -> None:
    metric = ranking_metrics(
        (_result("old", 1), _result("distractor", 3)),
        gold_source_message_ids=("current",),
        superseded_source_message_ids=("old",),
        evaluation_top_k_messages=2,
    )
    assert metric.superseded_fact_retrieval_rate == 0.5
    assert metric.irrelevant_memory_injection_rate == 1.0


def test_answer_scorer_requires_current_value_and_rejects_superseded_value() -> None:
    from experiments.conversational_memory.dataset import AnswerExpectation

    expected = AnswerExpectation(("Helios-29",), ("Polaris-17",))
    assert answer_metrics("The answer is Helios-29.", expected).fact_consistency == 1.0
    contradictory = answer_metrics("It changed from Polaris-17 to Helios-29.", expected)
    assert contradictory.conversational_recall_accuracy == 1.0
    assert contradictory.fact_consistency == 0.0


def test_costs_propagate_missing_usage_and_zero_denominator() -> None:
    prices = PriceTable("USD", "2026-08-12", "g", 0.15, 0.6, "e", 0.02, ())
    assert generation_cost(input_tokens=None, output_tokens=1, prices=prices) is None
    assert embedding_cost(tokens=None, prices=prices) is None
    assert nullable_sum((0.1, None, 0.2)) is None
    assert api_cost_per_correct_recall(total_cost=0.5, correct_recall_count=0) == "undefined"


def test_abc_memory_cost_is_structural_zero_not_missing() -> None:
    prices = PriceTable("USD", "2026-08-12", "g", 0.15, 0.6, "e", 0.02, ())
    assert embedding_cost(tokens=0, prices=prices) == 0.0
    assert generation_cost(input_tokens=100, output_tokens=20, prices=prices) == pytest.approx(0.000027)


def test_break_even_requires_memory_to_stay_below_bounded_history() -> None:
    def ledger(arm: str, costs: list[float]) -> dict:
        return {
            "conversation_id": "c",
            "arm": arm,
            "steps": [
                {"cumulative_conversation_api_cost": cost} for cost in costs
            ],
        }

    result = compute_break_even(
        {
            "c:A": ledger("A", [1, 2, 3]),
            "c:B": ledger("B", [1, 3, 6]),
            "c:C": ledger("C", [1, 2, 3]),
            "c:D1": ledger("D1", [2, 2.5, 5]),
            "c:D2": ledger("D2", [2, 4, 5]),
        }
    )
    assert result["c:D1"]["break_even_exchange"] == 2
    assert result["c:D2"]["break_even_exchange"] == 3


def test_paired_bootstrap_is_deterministic_and_uses_step_pairing() -> None:
    selected = {"a": 1.0, "b": 1.0, "c": 0.0, "d": 1.0}
    comparator = {"a": 0.0, "b": 1.0, "c": 0.0, "d": 0.0}
    first = paired_bootstrap_interval(selected, comparator, samples=1000, seed=27)
    second = paired_bootstrap_interval(selected, comparator, samples=1000, seed=27)
    assert first == second
    assert first["mean_difference"] == 0.5
    assert first["step_count"] == 4


def test_heldout_guard_rejects_unsigned_registration() -> None:
    with pytest.raises(GuardFailure, match="not approved"):
        load_registration(REGISTRATION.resolve(), phase="heldout")


def test_development_registration_is_allowed_before_threshold_signoff() -> None:
    payload = load_registration(REGISTRATION.resolve(), phase="development")
    assert payload["decision_rule"]["thresholds"]["primary_break_even_exchange"] is None


def test_selection_follows_declared_recall_first_order() -> None:
    def report(recall: float, mrr: float, chars: int) -> dict:
        aggregate = {
            "recall_at_k": recall,
            "mrr": mrr,
            "delivered_unique_source_recall": recall,
            "irrelevant_memory_injection_rate": 0.0,
            "duplicate_chunk_slot_rate": 0.0,
            "mean_query_estimated_tokens": 10.0,
        }
        return {
            "candidate": {
                "chunk_max_chars": chars,
                "chunk_overlap_chars": 0,
                "recent_window_max_messages": 4,
                "retrieval_top_k_chunks": 4,
                "similarity_threshold": 0.2,
            },
            "aggregate": {"D1": copy.deepcopy(aggregate), "D2": copy.deepcopy(aggregate)},
            "isolation_failures": 0,
        }

    selected = select_candidate([report(0.7, 1.0, 240), report(0.8, 0.5, 1000)])
    assert selected["candidate"]["chunk_max_chars"] == 1000


def test_production_code_does_not_import_experiment_package() -> None:
    offenders: list[str] = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(name.startswith("experiments.conversational_memory") for name in names):
                offenders.append(str(path))
    assert offenders == []


def test_registration_contains_no_semantic_variant_or_cost() -> None:
    payload = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    serialized = json.dumps(payload).casefold()
    assert '"semantic_memory": false' in serialized
    assert "semantic_extraction_cost" not in serialized
    assert '"e"' not in payload["calibration"]["query_variants"]


def test_experiment_provider_serializes_assistant_history_as_string_content() -> None:
    provider = ConversationExperimentOpenAIProvider(
        OpenAIProviderConfig(api_key="test", model="model", timeout_s=1.0)
    )
    payload = provider._build_payload(
        ProviderInput(
            request_id=uuid4(),
            messages=(
                ChatMessage(role="user", content="first"),
                ChatMessage(role="assistant", content="answer"),
                ChatMessage(role="user", content="follow-up"),
            ),
        )
    )
    assert payload["input"][1] == {"role": "assistant", "content": "answer"}
    assert "input_text" not in json.dumps(payload)


def test_execution_ledger_is_append_only_and_reports_missing_usage(tmp_path: Path) -> None:
    ledger = ExecutionLedger(tmp_path / "events.jsonl", run_id="run", phase="development")
    embedding = ledger.started(operation="embedding", model="e", estimated_tokens=10)
    ledger.succeeded(embedding, estimated_tokens=10)
    generation = ledger.started(operation="generation", model="g", step_id="s", arm="A", repetition=1)
    ledger.succeeded(generation, actual_input_tokens=None, actual_output_tokens=None)
    failed = ledger.started(operation="generation", model="g", step_id="s", arm="B", repetition=1)
    ledger.failed(failed, error_kind="ProviderError", potentially_billable=False)
    summary = summarize_execution_ledger(ledger.path, run_id="run")
    assert summary["started_calls"] == 3
    assert summary["succeeded_calls"] == 2
    assert summary["failed_calls"] == 1
    assert summary["estimated_embedding_tokens"] == 10
    assert summary["missing_success_usage_calls"] == 1


def test_execution_summary_can_isolate_one_run(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    first = ExecutionLedger(path, run_id="first", phase="development")
    call = first.started(operation="embedding", model="e")
    first.succeeded(call, estimated_tokens=5)
    second = ExecutionLedger(path, run_id="second", phase="development")
    call = second.started(operation="embedding", model="e")
    second.succeeded(call, estimated_tokens=7)
    assert summarize_execution_ledger(path, run_id="first")["estimated_embedding_tokens"] == 5
    assert summarize_execution_ledger(path, run_id="second")["estimated_embedding_tokens"] == 7
