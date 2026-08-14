from __future__ import annotations

from pathlib import Path

from app.core.domain.provider import ProviderInput

from experiments.dual_conversational_memory.dataset import load_dataset
from experiments.dual_conversational_memory.external import DevelopmentOpenAIProvider
from experiments.dual_conversational_memory.memory import (
    ChunkProfile,
    SemanticFact,
    bm25_search,
    build_chunks,
    build_query,
    compose_input,
    exact_dense_search,
    fallback_reasons,
    generate_profiles,
    reciprocal_rank_fusion,
    stable_hash,
)
from experiments.dual_conversational_memory.protocol import load_manifest
from experiments.dual_conversational_memory.scorers import (
    answer_score,
    fallback_confusion,
    retrieval_score,
    semantic_extraction_score,
)
from app.core.providers.openai_provider import OpenAIProviderConfig


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "experiments/dual_conversational_memory/data/development.jsonl"


def _fixture():
    return load_dataset(DATA, expected_split="development")[0]


def test_frozen_profile_generator_has_exactly_thirty_stable_profiles() -> None:
    manifest = load_manifest()

    first = generate_profiles(manifest.payload)
    second = generate_profiles(manifest.payload)

    assert first == second
    assert len(first) == 30
    assert [item.profile_id for item in first] == [f"profile-{index:02d}" for index in range(30)]
    assert {item.chunk.max_chars for item in first} == {600, 1000}
    assert {item.rrf_c for item in first} == {10, 60}


def test_q2_text_is_deterministic_and_current_message_appears_once_last() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[1]
    prefix = fixture.prefix_before(evaluation.query_event_id)
    current, _ = fixture.query_and_reference(evaluation)

    query = build_query(
        variant="Q2-TEXT",
        current_user=current,
        prefix=prefix,
        recent_event_count=2,
        max_tokens=320,
    )

    assert query.text.count(current.content) == 1
    assert query.text.endswith(f"{current.content}\nEND_MEMORY_QUERY")
    assert current.message_id not in query.recent_event_ids


def test_exact_dense_filters_tenant_conversation_sequence_and_active_window() -> None:
    fixture = _fixture()
    chunks = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        events=fixture.events,
        unit_type="event",
        profile=ChunkProfile(1000, 0),
        index_version="test-v1",
    )
    vectors = {stable_hash(chunk.text): (1.0, 0.0) for chunk in chunks}

    results = exact_dense_search(
        chunks,
        vectors,
        (1.0, 0.0),
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=8,
        excluded_event_ids={fixture.events[6].event_id},
        threshold=0.5,
        limit=20,
    )

    assert results
    assert all(item.chunk.source_event_sequence < 8 for item in results)
    assert fixture.events[6].event_id not in {item.chunk.source_event_id for item in results}
    assert exact_dense_search(chunks, vectors, (1.0, 0.0), tenant_id="wrong", conversation_id=fixture.conversation_id, before_event_sequence=8, excluded_event_ids=set(), threshold=0.5, limit=20) == ()


def test_bm25_and_hybrid_have_deterministic_exact_identifier_ranking() -> None:
    fixture = _fixture()
    evaluation = next(item for item in fixture.evaluations if "exact_identifier" in item.slices)
    query, _ = fixture.query_and_reference(evaluation)
    chunks = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        events=fixture.events,
        unit_type="event",
        profile=ChunkProfile(1000, 0),
        index_version="test-v1",
    )
    lexical = bm25_search(
        chunks,
        query.content,
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        before_event_sequence=fixture.event_by_id(evaluation.query_event_id).sequence,
        excluded_event_ids=set(),
        k1=1.2,
        b=0.65,
        limit=12,
    )
    fused = reciprocal_rank_fusion((), lexical, constant=10, top_k=4)

    assert lexical[0].chunk.source_event_id in evaluation.gold_source_event_ids
    assert fused[0].chunk.chunk_id == lexical[0].chunk.chunk_id


def test_bm25_rejects_wrong_tenant_and_conversation() -> None:
    fixture = _fixture()
    chunks = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        events=fixture.events,
        unit_type="event",
        profile=ChunkProfile(1000, 0),
        index_version="test-v1",
    )

    wrong_tenant = bm25_search(
        chunks,
        "project code",
        tenant_id="another-tenant",
        conversation_id=fixture.conversation_id,
        before_event_sequence=12,
        excluded_event_ids=set(),
        k1=1.2,
        b=0.65,
        limit=12,
    )
    wrong_conversation = bm25_search(
        chunks,
        "project code",
        tenant_id=fixture.tenant_id,
        conversation_id="another-conversation",
        before_event_sequence=12,
        excluded_event_ids=set(),
        k1=1.2,
        b=0.65,
        limit=12,
    )

    assert wrong_tenant == ()
    assert wrong_conversation == ()


def test_retrieval_scoring_collapses_duplicate_chunks_by_event() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[0]
    chunks = build_chunks(
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        events=fixture.events,
        unit_type="event",
        profile=ChunkProfile(70, 10),
        index_version="tiny",
    )
    source = [chunk for chunk in chunks if chunk.source_event_id in evaluation.gold_source_event_ids]
    from experiments.dual_conversational_memory.memory import RankedChunk

    results = tuple(RankedChunk(chunk, 1.0 - index * 0.01) for index, chunk in enumerate(source))
    score = retrieval_score(results, evaluation=evaluation, evaluation_top_k_events=4)

    assert score.delivered_unique_events == 1
    assert score.recall_at_k == 1.0
    assert score.duplicate_chunk_slot_rate > 0


def test_semantic_scorer_penalizes_assistant_and_prohibited_extractions() -> None:
    fixture = _fixture()
    prohibited_event = fixture.events[10]
    gold = prohibited_event.gold_facts[0]
    extracted = SemanticFact(
        fact_id="fact",
        tenant_id=fixture.tenant_id,
        conversation_id=fixture.conversation_id,
        fact_key=gold.fact_key,
        value=gold.value,
        value_type=gold.value_type,
        source_event_id=prohibited_event.event_id,
        source_message_ids=tuple(message.message_id for message in prohibited_event.messages),
        source_role="user",
        confidence=0.99,
        effective_sequence=prohibited_event.sequence,
        status="active",
        supersedes_event_ids=(),
        extractor_version="test",
    )

    score = semantic_extraction_score(prohibited_event, (extracted,))

    assert score.false_positive == 1
    assert score.prohibited_extractions == 1


def test_answer_scorer_does_not_count_forbidden_substring_inside_required_value() -> None:
    from experiments.dual_conversational_memory.dataset import AnswerExpectation

    score = answer_score("The current value is $2,000.", AnswerExpectation(("$2,000",), ("$2",)))

    assert score.conversational_recall_accuracy == 1.0
    assert score.fact_consistency == 1.0


def test_context_fallback_replaces_memory_and_current_is_exactly_once() -> None:
    fixture = _fixture()
    evaluation = fixture.evaluations[1]
    prefix = fixture.prefix_before(evaluation.query_event_id)
    current, _ = fixture.query_and_reference(evaluation)

    context = compose_input(
        arm="G-FALLBACK",
        prefix=prefix,
        current_user=current,
        active_event_count=2,
        fallback=True,
        fallback_reason_codes=("registered_deictic_phrase",),
    )

    assert context.fallback_used is True
    assert context.episodic_chunk_ids == ()
    assert context.semantic_fact_ids == ()
    assert sum(message.content == current.content for message in context.messages) == 1
    assert context.messages[-1].role == "user"


def test_fallback_policy_and_confusion_are_gold_blind_and_deterministic() -> None:
    reasons = fallback_reasons(
        policy="deictic_or_no_result",
        query="What did we finally decide?",
        dense=(),
        lexical=(),
        semantic_facts=(),
    )
    metrics = fallback_confusion([(bool(reasons), True), (False, False)])

    assert reasons == ("registered_deictic_phrase", "no_result_above_threshold")
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0


def test_experiment_provider_payload_preserves_roles_and_output_cap() -> None:
    provider = DevelopmentOpenAIProvider(
        OpenAIProviderConfig(api_key="test", model="gpt-4o-mini", timeout_s=1, max_attempts=1),
        max_output_tokens=160,
    )
    context = compose_input(
        arm="B",
        prefix=_fixture().events[:2],
        current_user=_fixture().events[2].messages[0],
        active_event_count=2,
    )

    payload = provider._build_payload(ProviderInput(request_id=__import__("uuid").uuid4(), messages=context.messages))

    assert payload["max_output_tokens"] == 160
    assert [item["role"] for item in payload["input"]] == [message.role for message in context.messages]
    assert all(isinstance(item["content"], str) for item in payload["input"])
