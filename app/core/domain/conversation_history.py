from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from .types import Role


class HistoryIntegrityError(Exception):
    """A ``ConversationHistoryPort`` delivered messages out of contract.

    Raised when ``sequence`` is not strictly increasing. This guards the port
    contract, not production data: the SQL adapter orders by ``sequence``, so
    only a misbehaving implementation can trigger it.
    """


class ConversationNotFoundError(Exception):
    """The conversation does not exist, or is not owned by this tenant.

    The two cases are deliberately indistinguishable. ADR-004 §2 chose this so
    a cross-tenant request leaks no information about whether the resource
    exists; ORQ-38 preserves that. Do not split this into separate
    forbidden/not-found errors -- doing so reopens the existence oracle.
    """


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    """One persisted turn message, provider-neutral.

    Carries no timestamp: a timestamp is not an ordering key here and cannot
    corroborate order (``func.now()`` is transaction-stable, so both messages
    of a turn share one). ``sequence`` is the only ordering source.
    """

    sequence: int
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class AssembledHistory:
    """Bounded, ordered history. ``truncated`` means messages were dropped."""

    messages: tuple[HistoryMessage, ...]
    total_available: int
    truncated: bool


class ConversationHistoryPort(Protocol):
    """Ordered history for one conversation.

    Implementations MUST:

    - Validate that ``conversation_id`` is owned by ``tenant_id`` and raise
      ``ConversationNotFoundError`` if it is not. Returning an empty sequence
      for an unowned conversation is a contract violation: a caller cannot
      distinguish it from an empty conversation, so isolation would be
      silently lost.
    - Deliver messages ordered by a strictly increasing ``sequence``.

    Both clauses are contract, not adapter courtesy: a second implementation
    inherits them from here, not from ``SqlConversationHistoryAdapter``.
    """

    async def fetch_ordered(
        self, conversation_id: UUID, tenant_id: str
    ) -> Sequence[HistoryMessage]:
        ...


class ConversationHistoryAssembler:
    """Validates port output, then bounds it.

    No DB access, no FastAPI/HTTP semantics -- the port is injected.
    """

    def __init__(self, *, max_messages: int, max_chars: int) -> None:
        self._max_messages = max_messages
        self._max_chars = max_chars

    async def assemble(
        self, port: ConversationHistoryPort, conversation_id: UUID, tenant_id: str
    ) -> AssembledHistory:
        messages = tuple(await port.fetch_ordered(conversation_id, tenant_id))
        # Validate the full port output before bounding: validating after
        # truncation would let a violation among the dropped older messages
        # pass unseen.
        self._require_strictly_increasing(messages)

        total_available = len(messages)
        kept = self._apply_bounds(messages)
        return AssembledHistory(
            messages=kept,
            total_available=total_available,
            truncated=total_available > len(kept),
        )

    @staticmethod
    def _require_strictly_increasing(messages: Sequence[HistoryMessage]) -> None:
        for previous, current in zip(messages, messages[1:]):
            if current.sequence <= previous.sequence:
                raise HistoryIntegrityError(
                    "port delivered a non-increasing sequence: "
                    f"{previous.sequence} then {current.sequence}"
                )

    def _apply_bounds(
        self, messages: tuple[HistoryMessage, ...]
    ) -> tuple[HistoryMessage, ...]:
        # Message cap first, then the character cap; both drop from the oldest
        # end. The order is fixed because it changes which messages survive.
        kept = messages[-self._max_messages :] if messages else messages
        # Drop whole messages from the oldest end until the budget fits, but
        # never return nothing: a single oversized message is surfaced with the
        # cap exceeded rather than swallowed.
        while len(kept) > 1 and sum(len(m.content) for m in kept) > self._max_chars:
            kept = kept[1:]
        return kept
