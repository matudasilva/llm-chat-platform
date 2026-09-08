"""ORQ-37 H2/AC14 fix -- the combined added-context budget actually combines.

Two independent terminal cases AC14's own text names but the shipped T13/T18
code never implemented, found by independent validation (`validation.md`,
Hallazgo H2) after ORQ-37's local closure:

1. Documental RAG context was never subtracted from
   `chat_prompt_max_added_context_chars` before packing the recent window --
   two separate ~12 000-char budgets, not one combined cap.
2. An oversized current user message did not force zero added context; the
   packer never even receives the current message (it is outside the budget
   by design), so nothing reacted to it being large.

Both fixes are in `app.api.deps.get_chat_memory_context`. Neither touches
Mode B's own ranking/selection, tracing, or `pack_recent_window`'s internal
packing rule -- only what gets passed into it.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import deps
from app.api.deps import get_chat_memory_context
from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import messages_for_provider, render_rag_sources_block
from app.core.domain.rag_generation import RagGenerationContext, RagSource
from app.http import pipeline_metrics

pytestmark = pytest.mark.asyncio

TENANT = "acme"
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Payload(SimpleNamespace):
    pass


def _payload(conversation_id=CONVERSATION_ID, message="current question"):
    return _Payload(conversation_id=conversation_id, message=message)


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


@pytest.fixture
def collector():
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(uuid.uuid4()), correlation_id=None
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


@pytest.fixture
def memory_on(monkeypatch):
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)
    return None


def _install_source(monkeypatch, result):
    """Same double `test_chat_memory_dependency.py` uses -- doubles only the
    port `fetch_ordered` calls, everything above it is shipped code."""

    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            if isinstance(result, BaseException):
                raise result
            return result

    class _Session:
        pass

    class _CM:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())


def _messages(*pairs):
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


def _rag_context(*contents: str) -> RagGenerationContext:
    # `_validated_sources` (provider_prompt.py) requires `citation == f"S{index}"`
    # exactly -- its defensive contract against untrusted/malformed metadata,
    # not this test's choice.
    return RagGenerationContext(
        sources=tuple(
            RagSource(
                citation=f"S{i}",
                document_id=uuid4(),
                chunk_id=uuid4(),
                rank=i,
                content=content,
                truncated=False,
            )
            for i, content in enumerate(contents, start=1)
        )
    )


# --- Measurement parity: the reservation must equal the actual render ------


async def test_documental_reservation_matches_the_actual_rendered_block() -> None:
    """The number reserved for documental RAG must equal what
    `messages_for_provider` actually renders -- not an approximation summing
    raw `RagSource.content`, which ignores `_RAG_INSTRUCTIONS`'s fixed length
    and each source's JSON structural overhead (citation, document_id,
    chunk_id, rank, truncated)."""
    rag_context = _rag_context("short passage", "a second, slightly longer passage")

    rendered = messages_for_provider(
        ProviderInput(request_id=uuid4(), messages=(), metadata=rag_context.provider_metadata)
    )
    actual_length = len(rendered[0].content)

    measured = len(
        render_rag_sources_block([s.provider_dict() for s in rag_context.sources])
    )

    assert measured == actual_length
    # And it is NOT the naive approximation this fix replaces -- proves the
    # test would have caught the original, wrong design.
    naive_sum = sum(len(s.content) for s in rag_context.sources)
    assert measured > naive_sum


async def test_reservation_is_zero_when_documental_contributed_nothing() -> None:
    empty_rag_context = RagGenerationContext()
    assert empty_rag_context.sources == ()
    # No sources -> messages_for_provider renders nothing for the rag channel
    # at all, so nothing should be reserved either.
    rendered = messages_for_provider(
        ProviderInput(request_id=uuid4(), messages=(), metadata=empty_rag_context.provider_metadata)
    )
    assert rendered == ()


# --- Fix A: documental usage reduces the window/evidence budget ------------


async def test_documental_usage_reduces_the_window_budget(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 200, raising=False)
    _install_source(monkeypatch, _messages(("user", "u" * 50), ("assistant", "a" * 50)))
    # 150 chars of documental usage leaves only 50 for the window -- less
    # than the 100 the window alone would need, so it must be dropped.
    rag_context = _rag_context("x" * (150 - len(render_rag_sources_block([]))))

    result = await get_chat_memory_context(
        _payload(), _request(), rag_context=rag_context
    )

    assert result.messages == ()
    assert collector.snapshot()["memory_outcome"] == "empty"


async def test_documental_usage_does_not_starve_a_window_that_still_fits(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 5000, raising=False)
    _install_source(monkeypatch, _messages(("user", "u" * 20), ("assistant", "a" * 20)))
    rag_context = _rag_context("small passage")

    result = await get_chat_memory_context(
        _payload(), _request(), rag_context=rag_context
    )

    assert len(result.messages) == 2
    assert collector.snapshot()["memory_outcome"] == "ok"


async def test_documental_at_full_cap_yields_zero_added_context(
    memory_on, collector, monkeypatch
) -> None:
    cap = 500
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", cap, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))
    # Documental alone renders to exactly the cap -- zero left for anything.
    instructions_overhead = len(render_rag_sources_block([]))
    rag_context = _rag_context("x" * (cap - instructions_overhead))

    result = await get_chat_memory_context(
        _payload(), _request(), rag_context=rag_context
    )

    assert result.messages == ()


async def test_no_rag_context_passed_directly_defaults_to_zero_reservation(
    memory_on, collector, monkeypatch
) -> None:
    """A direct unit-test call that never passes `rag_context` (35 pre-existing
    call sites across the suite) must behave exactly as before this fix --
    zero documental reservation, not a crash on a `Depends` marker object."""
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 5000, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))

    result = await get_chat_memory_context(_payload(), _request())

    assert len(result.messages) == 2


# --- Fix B: oversized current message -> zero added context ----------------


async def test_oversized_current_message_yields_zero_added_context(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 100, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))

    result = await get_chat_memory_context(
        _payload(message="x" * 100), _request()
    )

    assert result.messages == ()
    assert result.truncated is True
    assert collector.snapshot()["memory_outcome"] == "current_message_oversized"


async def test_current_message_one_char_under_the_cap_is_unaffected(
    memory_on, collector, monkeypatch
) -> None:
    """The negative case: proves the guard's threshold is exact, not
    off-by-one in either direction."""
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 100, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))

    result = await get_chat_memory_context(
        _payload(message="x" * 99), _request()
    )

    assert len(result.messages) == 2
    assert collector.snapshot()["memory_outcome"] == "ok"


async def test_mode_b_does_not_run_when_the_current_message_is_oversized(
    memory_on, collector, monkeypatch
) -> None:
    """Zero added context means zero -- Mode B must not even attempt
    retrieval, not merely find nothing to select."""
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 50, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))

    result = await get_chat_memory_context(
        _payload(message="x" * 50), _request()
    )

    assert result.retrieved_events == ()
    assert "ebm25_selected_count" not in collector.snapshot()
    assert collector.snapshot()["memory_outcome"] == "current_message_oversized"


async def test_zeroed_cap_is_reported_as_empty_not_oversized_message(
    memory_on, collector, monkeypatch
) -> None:
    """A degenerate boundary: `chat_prompt_max_added_context_chars <= 0` is
    unreachable in production (settings reject non-positive values) but is
    monkeypatched directly by a pre-existing test to exercise the window's
    own zero-budget packing. The oversized-current-message guard must not
    misclassify that pre-existing case."""
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 0, raising=False)
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))

    result = await get_chat_memory_context(_payload(), _request())

    assert result.messages == ()
    assert collector.snapshot()["memory_outcome"] == "empty"


# --- Determinism -------------------------------------------------------


async def test_combined_budget_result_is_byte_identical_across_two_runs(
    memory_on, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 300, raising=False)
    _install_source(monkeypatch, _messages(("user", "u" * 100), ("assistant", "a" * 100)))
    rag_context = _rag_context("a fixed documental passage")

    first = await get_chat_memory_context(_payload(), _request(), rag_context=rag_context)
    second = await get_chat_memory_context(_payload(), _request(), rag_context=rag_context)

    assert first.messages == second.messages
    assert first.truncated == second.truncated
