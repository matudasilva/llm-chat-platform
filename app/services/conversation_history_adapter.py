# app/services/conversation_history_adapter.py
from __future__ import annotations

from typing import Sequence
from uuid import UUID

from app.core.domain.conversation_history import (
    ConversationNotFoundError,
    HistoryMessage,
)
from app.services.conversation_query_service import ConversationQueryService


class SqlConversationHistoryAdapter:
    """``ConversationHistoryPort`` over ``ConversationQueryService``.

    Lives in ``app/services/`` rather than ``app/core/providers/`` -- the
    convention for port implementations -- because it composes an existing
    service over the app's own database, not an external provider behind a
    network boundary. ADR-011 records the deviation.
    """

    def __init__(self, queries: ConversationQueryService) -> None:
        self._queries = queries

    async def fetch_ordered(
        self, conversation_id: UUID, tenant_id: str
    ) -> Sequence[HistoryMessage]:
        # Layer 1, unconditional. ADR-004 §3 held tenant safety at the route
        # level and named this exact case -- "if it is ever called from a
        # context where conversation ownership was not pre-validated". This
        # component is consumed off-route, so the guard lives here.
        conversation = await self._queries.get_conversation(conversation_id, tenant_id)
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))

        rows = await self._queries.list_messages_for_conversation(
            conversation_id, tenant_id
        )
        # ``MessageRole`` subclasses ``str``, so passing the member through
        # would satisfy every ``==`` assertion while staying an enum
        # downstream. ``.value`` is required, not stylistic.
        return [
            HistoryMessage(
                sequence=row.sequence,
                role=row.role.value,
                content=row.content,
            )
            for row in rows
        ]
