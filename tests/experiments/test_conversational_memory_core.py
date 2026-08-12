from __future__ import annotations

from pathlib import Path

import pytest

from experiments.conversational_memory.dataset import load_dataset
from experiments.conversational_memory.memory import (
    ChunkingConfig,
    ContextBudgets,
    ExactMemoryIndex,
    MemoryChunk,
    RetrievedChunk,
    VectorizedChunk,
    build_chunks,
    build_memory_query,
    chronological_results,
    compose_context,
    fit_latest_messages,
)


DATASET = Path("experiments/conversational_memory/data/development.jsonl")


def _fixture():
    return load_dataset(DATASET, expected_split="development")[0]


def _budgets() -> ContextBudgets:
    return ContextBudgets(
        total_input_tokens=1024,
        system_tokens=160,
        conversation_tokens=640,
        active_window_tokens=320,
        episodic_memory_tokens=320,
        documentary_tokens=0,
        current_user_tokens=96,
        output_reserve_tokens=128,
        recent_window_max_messages=4,
    )


def _chunk(source: str, sequence: int, ordinal: int = 0, *, tenant: str = "t", conversation: str = "c") -> MemoryChunk:
    return MemoryChunk(
        artifact_id=f"a-{source}-{ordinal}",
        tenant_id=tenant,
        conversation_id=conversation,
        source_message_id=source,
        source_role="user" if sequence % 2 else "assistant",
        source_sequence=sequence,
        chunk_ordinal=ordinal,
        start_offset=0,
        end_offset=4,
        content=f"content {source} {ordinal}",
        source_hash="s",
        embedding_input_hash="e",
        index_version="v1",
    )


def test_chunk_rebuild_is_deterministic_and_bounded() -> None:
    fixture = _fixture()
    config = ChunkingConfig(240, 80, 4, "v1")
    first = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        messages=fixture.messages,
        config=config,
    )
    second = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        messages=fixture.messages,
        config=config,
    )
    assert first == second
    assert len({(item.source_message_id, item.chunk_ordinal, item.index_version) for item in first}) == len(first)
    counts: dict[str, int] = {}
    for item in first:
        counts[item.source_message_id] = counts.get(item.source_message_id, 0) + 1
    assert max(counts.values()) <= 4
    assert max(counts.values()) > 1  # The synthetic long-message fixture exercises chunking.


def test_d1_and_d2_queries_are_deterministic_and_exclude_current_user() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[1]
    current = fixture.message_by_id(evaluation.query_message_id)
    prefix = fixture.prefix_before(evaluation.query_message_id)
    active = fit_latest_messages(prefix, max_tokens=320, max_messages=4)
    d1 = build_memory_query(
        variant="D1", current_user=current, prefix=prefix, active_messages=active, max_tokens=256
    )
    d2 = build_memory_query(
        variant="D2", current_user=current, prefix=prefix, active_messages=active, max_tokens=256
    )
    assert d1.text == "What did we decide?"
    assert d2.text is not None
    assert d2.text.count("What did we decide?") == 1
    assert '"schema":"memory-query-v1"' in d2.text
    assert d2.included_source_sequences == (13, 14, 15, 16)
    assert build_memory_query(
        variant="D2", current_user=current, prefix=prefix, active_messages=active, max_tokens=256
    ) == d2


def test_d2_removes_oldest_whole_recent_messages_to_fit_budget() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[1]
    current = fixture.message_by_id(evaluation.query_message_id)
    prefix = fixture.prefix_before(evaluation.query_message_id)
    active = fit_latest_messages(prefix, max_tokens=320, max_messages=4)
    roomy = build_memory_query(
        variant="D2", current_user=current, prefix=prefix, active_messages=active, max_tokens=256
    )
    tight = build_memory_query(
        variant="D2", current_user=current, prefix=prefix, active_messages=active, max_tokens=80
    )
    assert tight.text is not None
    assert len(tight.included_source_sequences) < len(roomy.included_source_sequences)
    assert tight.included_source_sequences == tuple(sorted(tight.included_source_sequences))


def test_exact_retrieval_enforces_filters_exclusion_threshold_cap_and_ties() -> None:
    entries = [
        VectorizedChunk(_chunk("m1", 1, 0), (1.0, 0.0)),
        VectorizedChunk(_chunk("m1", 1, 1), (1.0, 0.0)),
        VectorizedChunk(_chunk("m2", 2, 0), (1.0, 0.0)),
        VectorizedChunk(_chunk("m3", 3, 0, tenant="other"), (1.0, 0.0)),
        VectorizedChunk(_chunk("m4", 4, 0, conversation="other"), (1.0, 0.0)),
        VectorizedChunk(_chunk("m5", 5, 0), (0.0, 1.0)),
    ]
    index = ExactMemoryIndex(entries)
    result = index.search(
        (1.0, 0.0),
        tenant_id="t",
        conversation_id="c",
        index_version="v1",
        excluded_source_message_ids={"m2"},
        similarity_threshold=0.5,
        retrieval_top_k_chunks=2,
        max_selected_chunks_per_source_message=2,
    )
    assert [(item.chunk.source_message_id, item.chunk.chunk_ordinal) for item in result] == [
        ("m1", 0),
        ("m1", 1),
    ]
    assert index.search(
        (1.0, 0.0),
        tenant_id="wrong",
        conversation_id="c",
        index_version="v1",
        excluded_source_message_ids=(),
        similarity_threshold=None,
        retrieval_top_k_chunks=4,
        max_selected_chunks_per_source_message=2,
    ) == ()


def test_relevance_selection_and_chronological_injection_are_distinct() -> None:
    relevance = (
        RetrievedChunk(_chunk("late", 9), 0.99),
        RetrievedChunk(_chunk("early", 1), 0.90),
    )
    assert [item.chunk.source_sequence for item in relevance] == [9, 1]
    assert [item.chunk.source_sequence for item in chronological_results(relevance)] == [1, 9]


def test_context_current_message_is_exactly_once_and_last() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[1]
    current = fixture.message_by_id(evaluation.query_message_id)
    prefix = fixture.prefix_before(evaluation.query_message_id)
    result = RetrievedChunk(
        _chunk("gold", 1, tenant=fixture.tenant_id, conversation=fixture.conversation_id),
        0.9,
    )
    context = compose_context(
        arm="D2", prefix=prefix, current_user=current, retrieved=(result,), budgets=_budgets()
    )
    assert context.messages[-1].role == "user"
    assert context.messages[-1].content == current.content
    assert sum(message.content == current.content for message in context.messages) == 1
    assert "untrusted historical transcript" in context.messages[1].content
    assert context.component_estimated_tokens["documentary_evidence"] == 0


def test_context_rejects_budget_overallocation() -> None:
    invalid = ContextBudgets(100, 50, 50, 30, 30, 0, 20, 20, 4)
    with pytest.raises(ValueError, match="exceed"):
        invalid.validate()
