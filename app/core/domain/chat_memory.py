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

from typing import Any

from .conversation_turns import WindowPartition
from .provider_prompt import MEMORY_SCHEMA_VERSION
from .types import ChatMessage


@dataclass(frozen=True, slots=True)
class RetrievedMemoryEvent:
    """One Mode B out-of-window turn selected for the evidence envelope (T18)."""

    event_id: int
    content: str

    def provider_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "content": self.content}


@dataclass(frozen=True, slots=True)
class ChatMemoryContext:
    """Ordered prior turns for one conversation. Empty means "no memory"."""

    messages: tuple[ChatMessage, ...] = ()
    truncated: bool = False
    # ORQ-37 T12 / AC36: True when the SQL read hit `conversation_history_max_rows`
    # -- a bound distinct from `truncated`, which is the assembler's own
    # message/char cap (ORQ-38). At the SQL cap the Mode B corpus is explicitly
    # the capped set, never a silently truncated one.
    history_row_cap_reached: bool = False
    # ORQ-37 T18 (Gate B2): Mode B's selected out-of-window evidence. Empty by
    # default -- Mode A (the shipped default, `ebm25_enabled=False`) never
    # populates this, which is what keeps AC16's byte-identity claim true by
    # construction rather than by a second code path.
    retrieved_events: tuple[RetrievedMemoryEvent, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.messages

    @property
    def provider_metadata(self) -> dict[str, Any] | None:
        """`metadata["memory"]`, rendered by `provider_prompt` (T17).

        `None` when there is nothing to render -- mirrors
        `RagGenerationContext.provider_metadata`'s own "no sources, no key"
        rule, and is what makes `messages_for_provider` emit no envelope at
        all rather than an empty one.
        """
        if not self.retrieved_events:
            return None
        return {
            "memory": {
                "schema_version": MEMORY_SCHEMA_VERSION,
                "events": [event.provider_dict() for event in self.retrieved_events],
            }
        }

    @classmethod
    def from_partition(
        cls,
        partition: WindowPartition,
        *,
        truncated: bool,
        history_row_cap_reached: bool = False,
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
            history_row_cap_reached=history_row_cap_reached,
        )
