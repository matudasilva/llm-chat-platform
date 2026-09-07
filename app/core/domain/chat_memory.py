"""Conversation memory context for one chat request (ORQ-37 T9, §Diseño 7).

The provider-neutral counterpart of `RagGenerationContext`: a frozen value
object the route can always hold, whose **empty instance is the safe default**.
Every failure path in `get_chat_memory_context` returns `ChatMemoryContext()`
rather than raising, which is what keeps invariant 7 intact -- see the module
docstring of `app/api/deps.py`.

Scope note: since T10 this carries the **materialized** window -- turn-snapped
and then well-formedness-filtered (§Diseño 8 steps 2-3). The hard
added-context cap is still T13's and nothing here anticipates it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conversation_turns import WindowPartition
from .types import ChatMessage


@dataclass(frozen=True, slots=True)
class ChatMemoryContext:
    """Ordered prior turns for one conversation. Empty means "no memory"."""

    messages: tuple[ChatMessage, ...] = ()
    truncated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.messages

    @classmethod
    def from_partition(
        cls, partition: WindowPartition, *, truncated: bool
    ) -> "ChatMemoryContext":
        """Materialize the well-formed window as ordered prior turns.

        Takes the partition rather than the raw `AssembledHistory` it took
        before T10: the assembler's output is message-atomic and can begin on
        any role, while what reaches the provider must be the snapped,
        filtered window (§Diseño 8). Converting from the assembler directly
        would put `system` rows and assistant-first openings into the turn
        list -- exactly what §Diseño 11 forbids.

        `HistoryMessage.role` is already a plain `Role` string (the adapter
        calls `.value` on the ORM enum), so no coercion happens here.
        `sequence` is dropped deliberately: it is the ordering key, not
        content, and the provider has no use for it.
        """
        return cls(
            messages=tuple(
                ChatMessage(role=message.role, content=message.content)
                for message in partition.window
            ),
            truncated=truncated,
        )
