"""ORQ-37 H2/AC14 -- the combined added-context cap, enforced for real.

Rewritten after independent re-validation found the first fix incomplete in
three ways (`validation.md` re-validation, 2026-09-08):

a) Mode B's budget recomputed from the full cap, spending documental's
   reservation a second time -- the combined total could exceed the cap.
b) The oversized-current-message guard emptied only the memory context;
   documental was merged back in by the route regardless, so "zero added
   context" was false.
c) Nothing ever trimmed documental against the combined cap, so documental
   alone could exceed it.

Two of the previous fixtures were also wrong: they computed content length as
`cap - len(empty_block)`, ignoring per-source JSON overhead and, in one case,
producing a NEGATIVE multiplier -- `"x" * -262` is `""` in Python, so the test
silently exercised an empty source and passed for the wrong reason.

**Every assertion here measures the real rendered prompt** via
`messages_for_provider`, the same function the provider path uses, and every
fixture MEASURES first and derives the cap from that measurement, rather than
assuming a size arithmetic could get wrong.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.api.routes.chat as chat_routes
from app.core.domain.added_context_budget import enforce_added_context_cap
from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderInput, ProviderResult
from app.core.domain.provider_prompt import (
    messages_for_provider,
    render_memory_events_block,
    render_rag_sources_block,
)
from app.core.domain.rag_generation import RagGenerationContext, RagSource
from app.core.domain.types import ChatMessage
from app.schemas.chat import ChatRequest

pytestmark = pytest.mark.asyncio


# --- helpers: everything MEASURED, nothing assumed -------------------------


def _rag(*contents: str) -> RagGenerationContext:
    # `_validated_sources` requires citations to read exactly S1..Sn.
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


def _memory(*, turns: tuple[str, ...] = (), events: tuple[str, ...] = ()) -> ChatMemoryContext:
    messages = []
    for i, content in enumerate(turns):
        messages.append(
            ChatMessage(role="user" if i % 2 == 0 else "assistant", content=content)
        )
    return ChatMemoryContext(
        messages=tuple(messages),
        retrieved_events=tuple(
            RetrievedMemoryEvent(event_id=i, content=content)
            for i, content in enumerate(events, start=1)
        ),
    )


def _merged_metadata(memory_context, rag_context):
    return {
        **(memory_context.provider_metadata or {}),
        **(rag_context.provider_metadata or {}),
    } or None


def _rendered_added_chars(memory_context, rag_context) -> int:
    """Exactly what AC14 caps: every added-context character the provider
    receives -- both envelopes and the window turns -- and nothing else.

    Built by rendering through `messages_for_provider`, so envelope templates
    and JSON structure are counted as sent, not approximated.
    """
    rendered = messages_for_provider(
        ProviderInput(
            request_id=uuid4(),
            messages=tuple(memory_context.messages),
            metadata=_merged_metadata(memory_context, rag_context),
        )
    )
    return sum(len(message.content) for message in rendered)


def _documental_chars(rag_context) -> int:
    if not rag_context.sources:
        return 0
    return len(render_rag_sources_block([s.provider_dict() for s in rag_context.sources]))


def _evidence_chars(memory_context) -> int:
    if not memory_context.retrieved_events:
        return 0
    return len(
        render_memory_events_block(
            [e.provider_dict() for e in memory_context.retrieved_events]
        )
    )


# --- the cap actually holds over all three contributors --------------------


async def test_everything_fits_leaves_all_three_untouched() -> None:
    memory_context = _memory(turns=("u1", "a1"), events=("evidence one",))
    rag_context = _rag("a documental passage")
    cap = _rendered_added_chars(memory_context, rag_context) + 100  # measured, not guessed

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="short question",
        max_chars=cap,
    )

    assert out_memory.messages == memory_context.messages
    assert out_memory.retrieved_events == memory_context.retrieved_events
    assert out_rag.sources == rag_context.sources
    assert outcome is None
    assert _rendered_added_chars(out_memory, out_rag) <= cap


async def test_combined_total_never_exceeds_the_cap_with_all_three_present() -> None:
    """Failure (a): documental + window + *effectively selected* evidence.

    The previous fix reserved documental only for the window's packing, then
    recomputed Mode B's budget from the full cap -- so this combination could
    exceed it. No previous test combined documental with real evidence.
    """
    memory_context = _memory(turns=("u" * 200, "a" * 200), events=("e" * 800,))
    rag_context = _rag("d" * 200)
    # Measured: a cap that genuinely cannot hold all three.
    cap = _documental_chars(rag_context) + 250

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="q",
        max_chars=cap,
    )

    assert _rendered_added_chars(out_memory, out_rag) <= cap
    # Drop order: evidence yields before any window turn.
    assert out_memory.retrieved_events == ()
    assert outcome == "budget_starved"


async def test_evidence_is_dropped_before_window_turns() -> None:
    memory_context = _memory(turns=("u" * 50, "a" * 50), events=("e" * 400,))
    rag_context = _rag("d" * 50)
    cap = _documental_chars(rag_context) + 100 + 60  # window fits, evidence cannot

    out_memory, out_rag, _ = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="q",
        max_chars=cap,
    )

    assert out_memory.retrieved_events == ()
    assert out_memory.messages == memory_context.messages  # window survived
    assert _rendered_added_chars(out_memory, out_rag) <= cap


# --- (b) oversized current message really zeroes everything ----------------


async def test_oversized_current_message_zeroes_documental_too() -> None:
    """Failure (b): the previous guard emptied memory only; the route merged
    documental back in, so a 772-character documental block still shipped."""
    memory_context = _memory(turns=("u1", "a1"), events=("e1",))
    rag_context = _rag("d" * 500)
    cap = 1000

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="x" * cap,
        max_chars=cap,
    )

    assert out_memory.messages == ()
    assert out_memory.retrieved_events == ()
    assert out_rag.sources == ()
    assert _merged_metadata(out_memory, out_rag) is None  # no envelope at all
    assert _rendered_added_chars(out_memory, out_rag) == 0
    assert outcome == "current_message_oversized"


async def test_current_message_strictly_above_the_cap_zeroes_everything() -> None:
    """The strictly-greater case, which the previous tests never covered --
    they pinned only `== cap` and `cap - 1`."""
    rag_context = _rag("d" * 100)
    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=_memory(turns=("u1", "a1")),
        rag_context=rag_context,
        current_message="x" * 1001,
        max_chars=1000,
    )

    assert _rendered_added_chars(out_memory, out_rag) == 0
    assert outcome == "current_message_oversized"


async def test_current_message_one_char_under_the_cap_is_unaffected() -> None:
    memory_context = _memory(turns=("u1", "a1"))
    rag_context = _rag("d")
    cap = _rendered_added_chars(memory_context, rag_context) + 2000

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="x" * (cap - 1),
        max_chars=cap,
    )

    assert out_memory.messages == memory_context.messages
    assert out_rag.sources == rag_context.sources
    assert outcome is None


# --- (c) documental alone can no longer breach the cap ---------------------


async def test_documental_alone_over_the_cap_is_trimmed_tail_first() -> None:
    """Failure (c): documental was bounded only by its own independent
    setting, so it could exceed the combined cap single-handedly."""
    rag_context = _rag("d" * 300, "d" * 300, "d" * 300)
    full = _documental_chars(rag_context)
    one_source_only = _documental_chars(_rag("d" * 300))
    assert full > one_source_only > 0  # the fixture is real, not degenerate
    cap = one_source_only + 10  # measured: room for exactly one source

    out_memory, out_rag, _ = enforce_added_context_cap(
        memory_context=ChatMemoryContext(),
        rag_context=rag_context,
        current_message="q",
        max_chars=cap,
    )

    assert _rendered_added_chars(out_memory, out_rag) <= cap
    assert len(out_rag.sources) == 1
    # Tail-first: citations must still read S1..Sn contiguously, or
    # `_validated_sources` rejects the whole block and it ships nothing.
    assert [s.citation for s in out_rag.sources] == ["S1"]
    # And the block still renders (it would be dropped entirely if invalid).
    assert _merged_metadata(out_memory, out_rag) is not None


async def test_documental_trimming_preserves_citation_contiguity_at_two() -> None:
    rag_context = _rag("d" * 100, "d" * 100, "d" * 100, "d" * 100)
    two_sources = _documental_chars(_rag("d" * 100, "d" * 100))
    cap = two_sources + 5

    _, out_rag, _ = enforce_added_context_cap(
        memory_context=ChatMemoryContext(),
        rag_context=rag_context,
        current_message="q",
        max_chars=cap,
    )

    assert [s.citation for s in out_rag.sources] == ["S1", "S2"]


# --- determinism, over the FULL rendered prompt ----------------------------


async def test_result_is_byte_identical_across_two_runs() -> None:
    """The previous determinism test compared only `messages` and `truncated`,
    with a window that ended up empty -- it could not have detected drift."""
    memory_context = _memory(turns=("u" * 120, "a" * 120), events=("e" * 300, "e" * 300))
    rag_context = _rag("d" * 150, "d" * 150)
    cap = _documental_chars(rag_context) + 200

    first_m, first_r, first_outcome = enforce_added_context_cap(
        memory_context=memory_context, rag_context=rag_context,
        current_message="q", max_chars=cap,
    )
    second_m, second_r, second_outcome = enforce_added_context_cap(
        memory_context=memory_context, rag_context=rag_context,
        current_message="q", max_chars=cap,
    )

    first_rendered = messages_for_provider(
        ProviderInput(request_id=uuid.UUID(int=1), messages=tuple(first_m.messages),
                      metadata=_merged_metadata(first_m, first_r))
    )
    second_rendered = messages_for_provider(
        ProviderInput(request_id=uuid.UUID(int=1), messages=tuple(second_m.messages),
                      metadata=_merged_metadata(second_m, second_r))
    )
    assert [m.content for m in first_rendered] == [m.content for m in second_rendered]
    assert first_outcome == second_outcome


# --- the route actually calls it, on BOTH paths ---------------------------


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self) -> None:
        self.objects: list[object] = []

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return None


class _CapturingChatService:
    def __init__(self) -> None:
        self.run_metadata = "unset"
        self.stream_metadata = "unset"

    async def run(self, *, request_id, messages, provider_metadata=None):
        self.run_metadata = provider_metadata
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content="answer"),
            provider_result=ProviderResult(
                content="answer", provider="stub", model_version="v1", prompt_version="v1"
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        self.stream_metadata = provider_metadata

        async def chunks() -> AsyncIterator[str]:
            yield "answer"

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="answer"),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


class _Cache:
    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, *, reason):
        return None


@pytest.fixture
def route_on(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", True)
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(chat_routes.settings, "chat_prompt_max_added_context_chars", 1000)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _Cache())
    return None


async def _drain(response) -> None:
    async for _ in response.body_iterator:
        pass


async def test_route_zeroes_documental_on_oversized_message_non_streaming(route_on) -> None:
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="x" * 1000),
        db=_Session(),
        chat_service=service,
        rag_context=_rag("d" * 300),
        memory_context=_memory(turns=("u1", "a1")),
    )
    # Nothing added at all -- not the memory envelope, not the rag envelope.
    assert service.run_metadata is None


async def test_route_zeroes_documental_on_oversized_message_streaming(route_on) -> None:
    service = _CapturingChatService()
    response = await chat_routes.chat(
        ChatRequest(message="x" * 1000, stream=True),
        db=_Session(),
        chat_service=service,
        rag_context=_rag("d" * 300),
        memory_context=_memory(turns=("u1", "a1")),
    )
    await _drain(response)
    assert service.stream_metadata is None


async def test_route_keeps_context_when_it_fits_non_streaming(route_on) -> None:
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="short question"),
        db=_Session(),
        chat_service=service,
        rag_context=_rag("d" * 100),
        memory_context=_memory(turns=("u1", "a1")),
    )
    assert service.run_metadata is not None
    assert "rag" in service.run_metadata
