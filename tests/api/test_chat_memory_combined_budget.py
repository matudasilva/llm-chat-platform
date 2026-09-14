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

**Assertions measure the rendered added context** via
`messages_for_provider`, the same function the provider path uses -- that is
the added-context prefix plus the window, which is exactly what AC14 caps; it
does NOT include the current user message, which is outside the budget by
design. Every fixture MEASURES first and derives the cap from that
measurement, rather than assuming a size arithmetic could get wrong.
"""
from __future__ import annotations

import dataclasses
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
    # The block must actually RENDER and CONTAIN the surviving source. A
    # renderer that silently discarded the whole block (which is what
    # `_validated_sources` does when citations are not contiguous) would still
    # satisfy a metadata-not-None plus total<=cap assertion, so assert on the
    # rendered text itself.
    rendered = messages_for_provider(
        ProviderInput(
            request_id=uuid4(),
            messages=(),
            metadata=_merged_metadata(out_memory, out_rag),
        )
    )
    assert len(rendered) == 1
    assert '"citation":"S1"' in rendered[0].content
    assert out_rag.sources[0].content in rendered[0].content


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
    rendered = messages_for_provider(
        ProviderInput(
            request_id=uuid4(), messages=(),
            metadata=_merged_metadata(ChatMemoryContext(), out_rag),
        )
    )
    assert '"citation":"S1"' in rendered[0].content
    assert '"citation":"S2"' in rendered[0].content
    assert '"citation":"S3"' not in rendered[0].content


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
        self.run_messages: list[ChatMessage] | None = None
        self.stream_messages: list[ChatMessage] | None = None

    async def run(self, *, request_id, messages, provider_metadata=None):
        self.run_metadata = provider_metadata
        self.run_messages = list(messages)
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content="answer"),
            provider_result=ProviderResult(
                content="answer", provider="stub", model_version="v1", prompt_version="v1"
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        self.stream_metadata = provider_metadata
        self.stream_messages = list(messages)

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
    # And prove it on the messages handed to ChatService (the layer below the
    # route; not a real provider payload, which `test_chat_memory_provider_input.py`
    # and the per-provider matrix of AC37 cover): only the current user
    # message, carried through untouched.
    assert [m.role for m in service.run_messages] == ["user"]
    assert service.run_messages[0].content == "x" * 1000


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
    assert [m.role for m in service.stream_messages] == ["user"]
    assert service.stream_messages[0].content == "x" * 1000


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
    # The window survived and precedes the current message.
    assert [m.content for m in service.run_messages] == ["u1", "a1", "short question"]


# --- N1: clearing memory must preserve the context's own metadata ----------


async def test_oversized_guard_preserves_row_cap_and_sets_truncated() -> None:
    """N1 (independent re-validation, 2026-09-08).

    The guard returned a fresh `ChatMemoryContext()`, which silently reset
    `history_row_cap_reached` -- a real persisted column describing what the
    SQL read did -- and left `truncated` false even though it had just dropped
    the entire window. AC14 requires `history_truncated=true` "whenever a turn
    is dropped or truncated".
    """
    memory_context = ChatMemoryContext(
        messages=(
            ChatMessage(role="user", content="u1"),
            ChatMessage(role="assistant", content="a1"),
        ),
        history_row_cap_reached=True,
    )

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=_rag("d" * 100),
        current_message="x" * 1000,
        max_chars=1000,
    )

    assert out_memory.messages == ()
    assert out_memory.truncated is True          # a turn was dropped
    assert out_memory.history_row_cap_reached is True  # never this function's to reset
    assert out_rag.sources == ()
    assert outcome == "current_message_oversized"


async def test_oversized_guard_keeps_truncated_false_when_there_was_no_window() -> None:
    """The mirror case: nothing was dropped, so nothing is claimed."""
    out_memory, _, _ = enforce_added_context_cap(
        memory_context=ChatMemoryContext(),
        rag_context=_rag("d" * 100),
        current_message="x" * 1000,
        max_chars=1000,
    )
    assert out_memory.truncated is False


async def test_oversized_guard_does_not_clear_a_previously_true_truncated() -> None:
    memory_context = ChatMemoryContext(truncated=True)
    out_memory, _, _ = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=_rag("d"),
        current_message="x" * 1000,
        max_chars=1000,
    )
    assert out_memory.truncated is True


# --- N2: the outcome follows the reduction, not the channel ----------------


async def test_window_wiped_by_documental_without_evidence_is_budget_starved() -> None:
    """N2 (independent re-validation, 2026-09-08).

    The override keyed on "was there evidence?", so a request whose entire
    window was dropped to fit documental kept the dependency's earlier `ok`:
    zero context shipped while telemetry still claimed a healthy window.
    """
    memory_context = _memory(turns=("u" * 100, "a" * 100))  # no evidence at all
    rag_context = _rag("d" * 2000)

    out_memory, _, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="q",
        max_chars=1000,
    )

    assert out_memory.messages == ()
    assert outcome == "budget_starved"


async def test_truncating_the_last_turn_is_also_budget_starved() -> None:
    """A per-channel emptiness check would miss this: nothing is emptied, the
    last retained turn is merely shortened -- still a reduction by the cap."""
    memory_context = _memory(turns=("u" * 400, "a" * 400))
    cap = 300

    out_memory, _, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=RagGenerationContext(),
        current_message="q",
        max_chars=cap,
    )

    assert out_memory.messages != ()          # not emptied
    assert _rendered_added_chars(out_memory, RagGenerationContext()) <= cap
    assert outcome == "budget_starved"


async def test_no_reduction_leaves_the_dependency_outcome_standing() -> None:
    memory_context = _memory(turns=("u1", "a1"))
    rag_context = _rag("d")
    cap = _rendered_added_chars(memory_context, rag_context) + 500

    _, _, outcome = enforce_added_context_cap(
        memory_context=memory_context, rag_context=rag_context,
        current_message="q", max_chars=cap,
    )
    assert outcome is None


# --- the degenerate cap ----------------------------------------------------


@pytest.mark.parametrize("cap", [0, -1])
async def test_non_positive_cap_zeroes_everything_and_reports_it(cap: int) -> None:
    memory_context = _memory(turns=("u1", "a1"), events=("e1",))
    memory_context = dataclasses.replace(memory_context, history_row_cap_reached=True)

    out_memory, out_rag, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=_rag("d" * 50),
        current_message="q",
        max_chars=cap,
    )

    assert _rendered_added_chars(out_memory, out_rag) == 0
    assert out_memory.truncated is True
    assert out_memory.history_row_cap_reached is True  # N1 applies here too
    assert outcome == "budget_starved"


@pytest.mark.parametrize("cap", [0, -1])
async def test_non_positive_cap_with_nothing_to_drop_reports_nothing(cap: int) -> None:
    _, _, outcome = enforce_added_context_cap(
        memory_context=ChatMemoryContext(),
        rag_context=RagGenerationContext(),
        current_message="q",
        max_chars=cap,
    )
    assert outcome is None


# --- AC14's literal evidence rule: every terminal case, run twice ----------


def _terminal_cases():
    """One fixture per AC14 terminal case, named, WITH its expected result.

    Expected values matter: an earlier version compared only two runs of the
    same input to each other, so every case still passed with the N1 and N2
    bugs reintroduced. Run-to-run equality detects non-determinism and
    nothing else; a deterministically wrong implementation satisfies it.
    Each row now carries the outcome and `truncated` it must produce.
    """
    return [
        (
            "within budget",
            _memory(turns=("u1", "a1"), events=("e1",)),
            _rag("d" * 20),
            "q",
            5000,
            None,       # expected outcome
            False,      # expected truncated
        ),
        (
            "evidence dropped",
            _memory(turns=("u" * 40, "a" * 40), events=("e" * 500,)),
            _rag("d" * 40),
            "q",
            _documental_chars(_rag("d" * 40)) + 120,
            "budget_starved",
            False,      # evidence is not history; no turn was dropped
        ),
        (
            "oldest turns dropped",
            _memory(turns=("u" * 100, "a" * 100, "u" * 30, "a" * 30)),
            RagGenerationContext(),
            "q",
            120,
            "budget_starved",
            True,
        ),
        (
            "last retained turn truncated",
            _memory(turns=("u" * 400, "a" * 400)),
            RagGenerationContext(),
            "q",
            300,
            "budget_starved",
            True,
        ),
        (
            "documental trimmed tail-first",
            ChatMemoryContext(),
            _rag("d" * 200, "d" * 200, "d" * 200),
            "q",
            _documental_chars(_rag("d" * 200)) + 10,
            "budget_starved",
            False,      # no history existed to truncate
        ),
        (
            "oversized current message",
            _memory(turns=("u1", "a1"), events=("e1",)),
            _rag("d" * 100),
            "x" * 1000,
            1000,
            "current_message_oversized",
            True,       # N1: the whole window was dropped
        ),
        (
            "non-positive cap",
            _memory(turns=("u1", "a1")),
            _rag("d" * 10),
            "q",
            0,
            "budget_starved",
            True,
        ),
    ]


@pytest.mark.parametrize(
    "label,memory_context,rag_context,current_message,cap,expected_outcome,expected_truncated",
    _terminal_cases(),
    ids=[case[0] for case in _terminal_cases()],
)
async def test_each_terminal_case_is_byte_identical_across_two_runs(
    label, memory_context, rag_context, current_message, cap,
    expected_outcome, expected_truncated,
) -> None:
    """AC14's evidence rule: "One fixture per terminal case, each run twice
    and compared". Compared on the FULL rendered prompt, not on two fields."""

    def _run():
        m, r, outcome = enforce_added_context_cap(
            memory_context=memory_context,
            rag_context=rag_context,
            current_message=current_message,
            max_chars=cap,
        )
        rendered = messages_for_provider(
            ProviderInput(
                request_id=uuid.UUID(int=7),
                messages=tuple(m.messages),
                metadata=_merged_metadata(m, r),
            )
        )
        window_roles = [msg.role for msg in m.messages]
        return (
            [x.content for x in rendered],
            outcome,
            m.truncated,
            m.history_row_cap_reached,
            window_roles,
        )

    first = _run()
    second = _run()
    assert first == second
    # Expected VALUES, not just run-to-run equality.
    assert first[1] == expected_outcome, label
    assert first[2] is expected_truncated, label
    # Roles survive every terminal case, including truncation of the last
    # retained turn. Asserted as strict user/assistant ALTERNATION starting on
    # `user` (§Diseño 8's well-formed window, §Diseño 11's alternation
    # contract) -- a weaker "every role is one of two values" check passes
    # even when every retained message has been rewritten to the same role,
    # which an audit mutation of the packer demonstrated.
    window_roles = first[4]
    assert window_roles == ["user", "assistant"] * (len(window_roles) // 2), label
    # And the cap holds in every terminal case.
    rendered_chars = sum(len(c) for c in first[0])
    if cap > 0:
        assert rendered_chars <= cap
    else:
        assert rendered_chars == 0


# --- R2: turn-snap must not leave a false history_truncated ---------------


async def test_turn_snap_restoring_the_window_clears_the_truncated_flag(
    monkeypatch,
) -> None:
    """R2 (independent re-validation, 2026-09-09).

    With `conversation_history_max_messages=1` over `[user, assistant]`, the
    assembler drops the `user` message and §Diseño 8's turn-snap puts it
    back. Both messages ship intact, so claiming a truncation is a false
    positive: AC14 says `history_truncated=true` "whenever a turn is dropped
    or truncated", which is a *whenever*, not an *at least whenever*.

    Driven through the real assembler, the real partition builder and the
    real dependency -- only the port is doubled, so the snap is shipped code.
    """
    from app.api import deps
    from app.core.domain.conversation_history import HistoryMessage

    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 1, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")

    history = [
        HistoryMessage(sequence=1, role="user", content="u1"),
        HistoryMessage(sequence=2, role="assistant", content="a1"),
    ]

    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return history

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())

    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid4(), message="q"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    # Nothing was lost: the snap restored the whole turn.
    assert [m.content for m in result.messages] == ["u1", "a1"]
    assert result.truncated is False


async def test_a_genuinely_bounded_window_still_reports_truncated(monkeypatch) -> None:
    """The mirror: when the bound really does drop a turn, the flag stands."""
    from app.api import deps
    from app.core.domain.conversation_history import HistoryMessage

    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")

    history = [
        HistoryMessage(sequence=1, role="user", content="old-u"),
        HistoryMessage(sequence=2, role="assistant", content="old-a"),
        HistoryMessage(sequence=3, role="user", content="new-u"),
        HistoryMessage(sequence=4, role="assistant", content="new-a"),
    ]

    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return history

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())

    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid4(), message="q"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    assert len(result.messages) < len(history)
    assert result.truncated is True


# --- partial evidence removal ---------------------------------------------


async def test_removing_only_some_evidence_still_reports_budget_starved() -> None:
    """Reduction is reduction: the outcome must not wait for the last event
    to go. Previously only full emptiness of a channel was considered."""
    memory_context = _memory(turns=("u1", "a1"), events=("e" * 200, "e" * 200, "e" * 200))
    rag_context = RagGenerationContext()
    # Measured: room for the window plus roughly one event, not three.
    one_event = _evidence_chars(_memory(events=("e" * 200,)))
    cap = one_event + 20

    out_memory, _, outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message="q",
        max_chars=cap,
    )

    assert 0 < len(out_memory.retrieved_events) < 3   # partial, not emptied
    assert outcome == "budget_starved"


async def test_turn_snap_under_cap_pressure_is_identical_across_two_runs(
    monkeypatch,
) -> None:
    """AC14's terminal-case evidence rule, applied to the turn-snap case.

    The re-validation of `d9cbeb7` found this specific gap: the turn-snap
    test above runs the dependency ONCE and restores a small turn that fits
    comfortably, so it never exercises snap -> cap pressure -> packing ->
    final prompt, and never compares two runs. AC14's evidence column asks
    for "One fixture per terminal case, each run twice and compared".

    Here the assembler's message bound drops the `user` message, §Diseño 8's
    turn-snap restores it, and the resulting window then EXCEEDS the hard cap,
    so the packer must act on a window the snap had just extended. Everything
    below the port is shipped code.
    """
    from app.api import deps
    from app.core.domain.conversation_history import HistoryMessage
    from app.http import pipeline_metrics

    history = [
        HistoryMessage(sequence=1, role="user", content="u" * 600),
        HistoryMessage(sequence=2, role="assistant", content="a" * 600),
    ]

    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return history

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 1, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_chars", 20000, raising=False)
    # After the snap the window holds 1 200 characters; the cap is 800, so the
    # packer must reduce a window the snap had just restored.
    monkeypatch.setattr(
        deps.settings, "chat_prompt_max_added_context_chars", 800, raising=False
    )
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")
    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())

    async def _run():
        instance, token = pipeline_metrics.init_collector(
            request_instance_id=str(uuid4()), correlation_id=None
        )
        try:
            context = await deps.get_chat_memory_context(
                SimpleNamespace(conversation_id=uuid4(), message="q"),
                SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            )
            rendered = messages_for_provider(
                ProviderInput(
                    request_id=uuid.UUID(int=11),
                    messages=tuple(context.messages),
                    metadata=_merged_metadata(context, RagGenerationContext()),
                )
            )
            return (
                [(m.role, m.content) for m in rendered],
                context.truncated,
                context.history_row_cap_reached,
                instance.snapshot()["memory_outcome"],
            )
        finally:
            pipeline_metrics.reset_collector(token)

    first = await _run()
    second = await _run()

    # Two runs, compared on the FINAL result: prompt contents and roles, both
    # history flags, and the recorded outcome.
    assert first == second

    rendered, truncated, row_cap, outcome = first
    added_chars = sum(len(content) for _, content in rendered)
    assert added_chars <= 800                    # the cap held after the snap
    assert truncated is True                     # the packer really did reduce
    assert row_cap is False
    assert outcome == "budget_starved"
    # The snap's restored turn is still a well-formed pair, roles intact.
    assert [role for role, _ in rendered] == ["user", "assistant"]
