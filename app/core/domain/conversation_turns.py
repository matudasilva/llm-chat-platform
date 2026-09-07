"""Turn grouping, snapping and the role-shape filter (ORQ-37 T10).

Three rules from the spec live here, in the order §Diseño 8 fixes them:

1. **Total grouping** (§Diseño 9). Walk messages in ascending ``sequence``; a
   ``user`` opens a turn and the immediately following ``assistant`` closes it;
   **any** other transition emits a singleton. No input is undefined -- §No-alcance
   forbids relying on any assumption about legacy message shape, so the rule
   must be total on arbitrary input rather than correct on well-behaved input.
2. **Snap back** (§Diseño 8 step 2). The assembler's bound is message-atomic
   and lands mid-turn in the normal case; the window is extended backwards to
   the start of the oldest turn it partially covers, so no retained turn is
   split.
3. **Well-formedness partition** (§Diseño 8 step 3 / §Diseño 11). The snapped
   span is split: well-formed ``user -> assistant`` units become the
   materialized window, everything else is returned to the caller as the
   complement.

Snapping alone does **not** give the alternation §Diseño 11 needs: snapping to
the start of a turn that is itself an assistant-first singleton yields an
assistant-first window. The filter, not the snap, is what guarantees the shape.

This module is a **reusable primitive**, deliberately: T16 needs the identical
grouping rule for the BM25 corpus, and two implementations of a rule this
fiddly would diverge. It knows nothing about ranking, retrieval or gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .conversation_history import HistoryMessage

_USER = "user"
_ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class TurnUnit:
    """One grouped unit. Well-formed means exactly ``user`` then ``assistant``."""

    messages: tuple[HistoryMessage, ...]

    @property
    def first_sequence(self) -> int:
        return self.messages[0].sequence

    @property
    def is_well_formed(self) -> bool:
        return (
            len(self.messages) == 2
            and self.messages[0].role == _USER
            and self.messages[1].role == _ASSISTANT
        )

    @property
    def document_text(self) -> str:
        # `"\n".join(contents)` in every case, reproducing `Event.document_text()`
        # (`model.py:85-86`). Kept here so T16's corpus and this window agree by
        # construction rather than by two matching implementations.
        return "\n".join(message.content for message in self.messages)


@dataclass(frozen=True, slots=True)
class WindowPartition:
    """The result of §Diseño 8 steps 1-3, over the bounded grouped history.

    ``window_units`` and ``excluded_units`` partition the whole grouped set:
    the intersection is empty and the union is everything. `excluded_units`
    carries the units §Diseño 8 step 4 returns to the Mode B retrieval corpus,
    **including those lying inside the snapped span** -- which is what keeps
    the partition total. Nothing in Gate B1 consumes it; it exists so T15 does
    not have to recompute steps 1-3 and risk the ordering bug §Diseño 8
    documents, where a malformed turn inside the snap belonged to neither side.
    """

    window: tuple[HistoryMessage, ...]
    window_units: tuple[TurnUnit, ...]
    excluded_units: tuple[TurnUnit, ...]
    grouped: tuple[TurnUnit, ...]
    snapped_in_turns: int


def group_turns(messages: Sequence[HistoryMessage]) -> tuple[TurnUnit, ...]:
    """Group into turn units. Total on arbitrary input (§Diseño 9).

    Totality is the property that matters and it is asserted directly: the
    concatenation of every unit reproduces the input exactly, in order.
    """
    units: list[TurnUnit] = []
    index = 0
    count = len(messages)
    while index < count:
        current = messages[index]
        if (
            current.role == _USER
            and index + 1 < count
            and messages[index + 1].role == _ASSISTANT
        ):
            units.append(TurnUnit(messages=(current, messages[index + 1])))
            index += 2
            continue
        # Any other transition -- a second consecutive `user`, a leading
        # `assistant`, a `system` row, an odd tail -- emits a singleton. This
        # branch is not an error path; it is the rule.
        units.append(TurnUnit(messages=(current,)))
        index += 1
    return tuple(units)


def build_materialized_window(
    *,
    all_messages: Sequence[HistoryMessage],
    bounded_messages: Sequence[HistoryMessage],
) -> WindowPartition:
    """Group once, snap the bound back to a turn boundary, then filter.

    ``all_messages`` is the SQL-bounded `fetch_ordered` output -- §Diseño 8
    step 1 groups *that*, not the assembler's already-bounded slice, because
    grouping the remainder after bounding can yield different boundaries than
    grouping the whole.
    """
    grouped = group_turns(all_messages)
    if not grouped or not bounded_messages:
        # No window at all: every unit is complement. Stated explicitly rather
        # than falling out of the slicing below, because "empty window" and
        # "window covering nothing" must not be allowed to differ.
        return WindowPartition(
            window=(),
            window_units=(),
            excluded_units=grouped,
            grouped=grouped,
            snapped_in_turns=0,
        )

    bound_start = bounded_messages[0].sequence
    snap_index = _index_of_unit_covering(grouped, bound_start)
    snapped_span = grouped[snap_index:]

    # The snap extended the window backwards iff the covering unit begins
    # earlier than the assembler's bound did.
    snapped_in = 1 if snapped_span[0].first_sequence < bound_start else 0

    window_units = tuple(unit for unit in snapped_span if unit.is_well_formed)
    excluded_units = tuple(grouped[:snap_index]) + tuple(
        unit for unit in snapped_span if not unit.is_well_formed
    )
    window = tuple(
        message for unit in window_units for message in unit.messages
    )
    return WindowPartition(
        window=window,
        window_units=window_units,
        excluded_units=excluded_units,
        grouped=grouped,
        snapped_in_turns=snapped_in,
    )


def _index_of_unit_covering(grouped: Sequence[TurnUnit], sequence: int) -> int:
    """Index of the unit containing `sequence`, or of the first one after it.

    The fallback matters: the assembler bounds by message, so its first
    retained message is always present in some unit -- but a caller passing a
    bound that no unit covers (an empty grouped set is handled above) must
    still get a defined answer rather than an IndexError.
    """
    for index, unit in enumerate(grouped):
        if any(message.sequence == sequence for message in unit.messages):
            return index
    for index, unit in enumerate(grouped):
        if unit.first_sequence >= sequence:
            return index
    return len(grouped)
