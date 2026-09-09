"""The single enforcement point for AC14's hard added-context cap.

**Why this module exists.** §Diseño 7's "Combined budget" covers three
contributors -- the recent-window turns, Mode B's retrieved conversational
evidence, and the documental RAG context -- but they are produced in two
different places: `get_chat_memory_context` builds the first two, while
`get_chat_rag_context` builds the third, as an independent FastAPI
dependency neither can see from inside the other. Only the route sees all
three, and only immediately before it assembles `provider_metadata`.

Two successive fixes tried to enforce the cap from inside the memory
dependency and both were incomplete, for the same structural reason: with
enforcement split across two places, the halves silently disagree. This
module is the correction -- one function, called once, at the one point where
all three contributors are known.

**The cap is measured on rendered text, not raw content.** The documental and
evidence channels each travel to the provider inside a system-message
envelope with fixed instruction text and JSON structural overhead
(`render_rag_sources_block`, `render_memory_events_block`); measuring their
raw `.content` understates what is actually sent by hundreds of characters
per item. Recent-window turns carry no envelope -- they enter the messages
list verbatim -- so their raw character sum is exact. Because a block's
rendered length is not linear in its item count (one fixed template plus
per-item JSON), every drop below re-measures rather than subtracting an
estimate.

**Drop order (§Diseño 7, applied in order until the added context fits):**

1. Out-of-window retrieved evidence, newest-selected first.
2. Oldest complete recent turns, whole turns at a time.
3. Deterministic truncation of the last retained turn.
4. **Documental sources, tail-first -- last resort only** (operator decision,
   2026-09-08). Documental is the most-protected contributor: it is resolved
   and bounded independently, and steps 1-3 must have already reduced
   everything else to zero before this applies. Without this step the cap
   cannot be *hard* at all, because documental alone can exceed it.
   Tail-first is mandatory, not stylistic: `_validated_sources` requires
   citations to read exactly `S1..Sn` contiguously, so dropping from the end
   preserves the contract while dropping from the middle would invalidate the
   whole block and silently discard all of it.

**The current user message is never touched.** It is outside the budget
entirely (ADR-011 §6): it is the request, not context. When it alone is
oversized, every added-context channel yields zero -- including documental,
which an earlier fix left in place because it could only reach the memory
context from where it ran.
"""

from __future__ import annotations

import dataclasses

from .chat_memory import ChatMemoryContext
from .context_packer import pack_recent_window
from .provider_prompt import render_memory_events_block, render_rag_sources_block
from .rag_generation import RagGenerationContext

# Outcome overrides this function can produce. Both already exist in the
# `memory_outcome` vocabulary; neither is new, and the column is a bare
# `String(64)` with no enum constraint, so nothing here needs a migration.
OUTCOME_CURRENT_MESSAGE_OVERSIZED = "current_message_oversized"
OUTCOME_BUDGET_STARVED = "budget_starved"


def _documental_chars(rag_context: RagGenerationContext) -> int:
    if not rag_context.sources:
        return 0
    return len(
        render_rag_sources_block([source.provider_dict() for source in rag_context.sources])
    )


def _evidence_chars(memory_context: ChatMemoryContext) -> int:
    if not memory_context.retrieved_events:
        return 0
    return len(
        render_memory_events_block(
            [event.provider_dict() for event in memory_context.retrieved_events]
        )
    )


def _window_chars(memory_context: ChatMemoryContext) -> int:
    # No envelope: window turns enter the messages list as plain ChatMessages,
    # so the raw sum is exactly what is sent.
    return sum(len(message.content) for message in memory_context.messages)


def enforce_added_context_cap(
    *,
    memory_context: ChatMemoryContext,
    rag_context: RagGenerationContext,
    current_message: str,
    max_chars: int,
) -> tuple[ChatMemoryContext, RagGenerationContext, str | None]:
    """Trim added context until the rendered total fits `max_chars`.

    Returns both contexts (trimmed as needed) and a `memory_outcome` override,
    or `None` when the outcome the memory dependency already recorded still
    stands. The caller records the override; recording it here would put a
    telemetry writer in the domain layer, and letting the dependency's earlier
    outcome stand after this function drops everything it selected is exactly
    the kind of stale-telemetry defect H1 was.

    The override is `budget_starved` whenever the cap actually reduced the
    added context -- any channel, including truncation of the last retained
    turn -- and `current_message_oversized` only for that one terminal case.
    No new outcome value is introduced.
    """
    # AC14's oversized-current-message terminal case: "yields zero added
    # context and an untouched request". Zero means all three channels, which
    # is why this runs here and not inside the memory dependency.
    #
    # The spec says "exceeds"; this implements `>=`, which is strictly more
    # conservative -- it also zeroes the exact-equality boundary. Disclosed
    # rather than silently chosen: the spec does not pin the comparison, and
    # the request itself is untouched either way.
    if max_chars > 0 and len(current_message) >= max_chars:
        # N1 (independent re-validation): clear the *contents* with
        # `dataclasses.replace`, never by returning a fresh
        # `ChatMemoryContext()`. A fresh instance silently resets
        # `history_row_cap_reached` -- a real persisted column describing what
        # the SQL read did, which this function has no business overwriting --
        # and drops a `truncated=True` the assembler had already recorded.
        # AC14 also requires `history_truncated=true` "whenever a turn is
        # dropped or truncated", and dropping the whole window to zero is the
        # most complete drop there is.
        return (
            dataclasses.replace(
                memory_context,
                messages=(),
                retrieved_events=(),
                truncated=memory_context.truncated or bool(memory_context.messages),
            ),
            dataclasses.replace(rag_context, sources=()),
            OUTCOME_CURRENT_MESSAGE_OVERSIZED,
        )

    def _total() -> int:
        return (
            _documental_chars(rag_context)
            + _window_chars(memory_context)
            + _evidence_chars(memory_context)
        )

    # N2 (independent re-validation): the outcome override is driven by
    # whether this function actually REDUCED the added context, measured, not
    # by which channel happened to hold it. The first version keyed it on
    # "was there evidence?", so a request whose entire window was dropped to
    # make room for documental kept the dependency's earlier `ok` -- zero
    # context shipped while telemetry still claimed a healthy window. That is
    # the same stale-telemetry defect H1 was, in a different field.
    # A single before/after comparison also covers truncation of the last
    # retained turn, which no per-channel emptiness check would notice.
    before_total = _total()

    # A non-positive cap is unreachable in production (settings reject it) but
    # is monkeypatched directly in tests. Treated as "no budget at all":
    # everything added is dropped, the request still untouched. Falls through
    # to the same reduction check below rather than returning early, so its
    # outcome is decided by the one rule.
    if max_chars <= 0:
        memory_context = dataclasses.replace(
            memory_context,
            messages=(),
            retrieved_events=(),
            truncated=memory_context.truncated or bool(memory_context.messages),
        )
        rag_context = dataclasses.replace(rag_context, sources=())
        return (
            memory_context,
            rag_context,
            OUTCOME_BUDGET_STARVED if before_total > 0 else None,
        )

    # Step 1 -- drop retrieved evidence, newest-selected first. `retrieved_events`
    # is in selection order, so the newest selection is the last element.
    while _total() > max_chars and memory_context.retrieved_events:
        memory_context = dataclasses.replace(
            memory_context, retrieved_events=memory_context.retrieved_events[:-1]
        )

    # Steps 2 and 3 -- drop oldest whole turns, then truncate the last retained
    # turn. `pack_recent_window` already implements both deterministically,
    # preserving roles and never splitting a retained pair; it is reused here
    # rather than reimplemented, with everything else that still occupies the
    # budget passed as `reserved_chars`.
    if _total() > max_chars:
        reserved = _documental_chars(rag_context) + _evidence_chars(memory_context)
        packed = pack_recent_window(
            memory_context.messages, max_chars=max_chars, reserved_chars=reserved
        )
        memory_context = dataclasses.replace(
            memory_context,
            messages=packed.messages,
            truncated=memory_context.truncated or packed.truncated,
        )

    # Step 4 -- documental, tail-first, last resort. Only reachable once the
    # window and evidence are already empty, i.e. documental alone exceeds the
    # cap. Re-measured each drop because the rendered length is not linear in
    # the source count.
    while _total() > max_chars and rag_context.sources:
        rag_context = dataclasses.replace(rag_context, sources=rag_context.sources[:-1])

    outcome = OUTCOME_BUDGET_STARVED if _total() < before_total else None
    return memory_context, rag_context, outcome
