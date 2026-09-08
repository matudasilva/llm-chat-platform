"""The hard added-context cap packer (ORQ-37 T13, §Diseño 7 "Combined budget").

`chat_prompt_max_added_context_chars` is a hard cap on the **added context**
only -- never on the current user message, which is outside this budget
entirely and is never truncated or dropped. ADR-011's own history cap is
**not** hard (`conversation_history.py:119-121` stops at `len(kept) > 1`, so
one oversized message survives it), and §Diseño 8's turn snap can extend the
window by up to one whole turn on top of that -- so a hard cap needs a total
packing rule downstream of both, not a second soft one.

The rule, applied in order until the added context fits:

1. Drop out-of-window retrieved evidence, newest-selected last. **The window
   is protected, not squeezed, to make room for it**: T18 packs THIS window
   first, against the full combined cap (`reserved_chars=0`, unchanged), and
   only then packs evidence against whatever remains. An earlier draft of this
   docstring assumed the opposite -- evidence's usage subtracted from the
   window's own budget via `reserved_chars` -- which would have dropped window
   turns before evidence, the reverse of the order this section states.
   `reserved_chars` stays unused for evidence; it remains available only for a
   genuinely independent future contributor to this same cap (documental RAG
   context, per §Diseño 7's "Combined budget" -- still not wired).
2. Drop oldest complete recent turns, whole turns at a time.
3. If the single remaining turn still exceeds the cap, truncate its content
   deterministically until the cap is met.

Invariants: roles are preserved -- truncation never changes a message's role
or drops one of a retained pair, so §Diseño 11's alternation contract
survives; the terminal state when nothing fits is *zero added context*, never
a truncated request; and this function never sees the current user message at
all, which is what keeps it untouched by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from app.core.utils.limits import truncate

from .types import ChatMessage


@dataclass(frozen=True, slots=True)
class PackedWindow:
    """The recent window after the hard cap has been applied.

    ``truncated`` is True whenever step 2 or step 3 fired -- a turn was
    dropped, or the last retained turn's content was cut -- mirroring AC14's
    "history_truncated=true is recorded whenever a turn is dropped or
    truncated".
    """

    messages: tuple[ChatMessage, ...]
    truncated: bool


def pack_recent_window(
    messages: Sequence[ChatMessage], *, max_chars: int, reserved_chars: int = 0
) -> PackedWindow:
    """Enforce the hard cap on a materialized recent window.

    ``messages`` MUST already be T10's well-formedness-filtered window: a flat
    sequence of complete ``(user, assistant)`` pairs in chronological order,
    with no partial turn. This function relies on that invariant to drop and
    truncate whole turns rather than individual messages, and does not
    re-validate it -- T10's `build_materialized_window` is what guarantees it.

    ``reserved_chars`` is budget already spent by another contributor to the
    same hard cap (documental RAG context, once wired). Zero means the whole
    cap is available to this window alone, which is this task's scope.
    """
    budget = max_chars - reserved_chars
    if budget <= 0:
        # Zero added context, not a one-turn window truncated down to empty
        # content: no room exists for anything, so nothing is retained.
        return PackedWindow(messages=(), truncated=bool(messages))

    turns = [tuple(messages[i : i + 2]) for i in range(0, len(messages), 2)]
    truncated = False

    # Step 2: drop the oldest whole turn, repeatedly, until it fits or only
    # one turn is left to (possibly) truncate in step 3.
    while len(turns) > 1 and _total_chars(turns) > budget:
        turns.pop(0)
        truncated = True

    if not turns:
        return PackedWindow(messages=(), truncated=truncated)

    # Step 3: the single remaining turn may still exceed the budget.
    if _total_chars(turns) > budget:
        truncated = True
        turns = [tuple(_truncate_turn(turns[0], budget))]

    flattened = tuple(message for turn in turns for message in turn)
    return PackedWindow(messages=flattened, truncated=truncated)


def _total_chars(turns: list[tuple[ChatMessage, ...]]) -> int:
    return sum(len(message.content) for turn in turns for message in turn)


def _truncate_turn(
    turn: tuple[ChatMessage, ...], budget: int
) -> list[ChatMessage]:
    """Truncate a turn's messages in order until `budget` characters remain.

    Walks the turn in its own role order (user, then assistant) rather than
    truncating a joined blob and re-splitting it: each message keeps its own
    role and identity, satisfying "truncation never changes a message's role
    or drops one of a retained pair" even in the degenerate case where the
    remaining budget reaches zero partway through -- the later message is
    still present, just empty, never removed.
    """
    packed: list[ChatMessage] = []
    remaining = budget
    for message in turn:
        if remaining <= 0:
            packed.append(replace(message, content=""))
            continue
        if len(message.content) <= remaining:
            packed.append(message)
            remaining -= len(message.content)
        else:
            packed.append(replace(message, content=truncate(message.content, remaining)))
            remaining = 0
    return packed
