"""The Mode B retrieval corpus (ORQ-37 T15, §Diseño 8 step 4).

`RetrievalCorpus` wraps `WindowPartition.excluded_units` (T10) with the
identity BM25 selection (T16) will need. Nothing here ranks or selects --
that is T16's "ranking, skip-and-continue selection". This module answers
only "what is the corpus" and "is it empty", per T15's task row.

The corpus is the bounded grouped history minus the MATERIALIZED window
(§Diseño 8 step 4) -- not minus the assembler's raw output, and not minus
every well-formed unit regardless of the snap. `WindowPartition` already
computed this correctly (T10): `excluded_units` includes every unit outside
`window_units`, including malformed units lying inside the snapped span,
which is what keeps `window ⊔ corpus` total. Recomputing it here would risk
reintroducing the exact ordering bug §Diseño 8 documents -- a malformed turn
inside the snap belonging to neither side -- so this module only re-packages
the partition T10 already proved total.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conversation_turns import TurnUnit, WindowPartition


@dataclass(frozen=True, slots=True)
class CorpusEvent:
    """One selectable unit of the Mode B corpus, identity-stable for T16.

    `event_id` is the turn's opening message's `sequence` -- unique and
    stable for a given conversation snapshot, mirroring how the experiment's
    `Event.event_id` identifies a turn (§Diseño 9's grouping produces exactly
    one first-message per unit, well-formed or not).
    """

    event_id: int
    unit: TurnUnit

    @property
    def document_text(self) -> str:
        return self.unit.document_text


@dataclass(frozen=True, slots=True)
class RetrievalCorpus:
    """The Mode B corpus: §Diseño 8 step 4, exposed for T16 to select from."""

    events: tuple[CorpusEvent, ...]

    @property
    def is_empty(self) -> bool:
        return not self.events

    @classmethod
    def from_partition(cls, partition: WindowPartition) -> "RetrievalCorpus":
        return cls(
            events=tuple(
                CorpusEvent(event_id=unit.first_sequence, unit=unit)
                for unit in partition.excluded_units
            )
        )
