"""Conversation memory context for one chat request (ORQ-37 T9, §Diseño 7).

The provider-neutral counterpart of `RagGenerationContext`: a frozen value
object the route can always hold, whose **empty instance is the safe default**.
Every failure path in `get_chat_memory_context` returns `ChatMemoryContext()`
rather than raising, which is what keeps invariant 7 intact -- see the module
docstring of `app/api/deps.py`.

Scope note: this carries the assembled window as ordered prior turns. The
turn-snapping rule and the role-shape contract of §Diseño 8/§Diseño 11 are
T10's, and the hard added-context cap is T13's. Nothing here anticipates them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conversation_history import AssembledHistory
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
    def from_assembled(cls, assembled: AssembledHistory) -> "ChatMemoryContext":
        # `HistoryMessage.role` is already a plain `Role` string (the adapter
        # calls `.value` on the ORM enum), so no further coercion happens here.
        # `sequence` is deliberately dropped: it is the ordering key, not
        # content, and the provider has no use for it.
        return cls(
            messages=tuple(
                ChatMessage(role=message.role, content=message.content)
                for message in assembled.messages
            ),
            truncated=assembled.truncated,
        )
