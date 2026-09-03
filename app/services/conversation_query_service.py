# app/services/conversation_query_service.py
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message


@dataclass(frozen=True)
class ConversationListRow:
    conversation_id: UUID
    created_at: object
    updated_at: object
    message_count: int


class ConversationQueryService:
    """
    Read-only query surface for conversations/messages.

    Constraints:
    - No writes
    - No schema assumptions beyond existing models
    - No FastAPI/HTTP semantics
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_conversation(self, conversation_id: UUID, tenant_id: str) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        res = await self._db.execute(stmt)
        conv = res.scalar_one_or_none()
        if conv is not None and conv.tenant_id != tenant_id:
            return None
        return conv

    async def list_messages_for_conversation(self, conversation_id: UUID, tenant_id: str) -> list[Message]:
        # ORQ-38 (T3 measured 0 divergent rows): query-level tenant scoping,
        # amending ADR-004 §3, which deliberately omitted this filter while the
        # route guard was the single call site. It no longer is.
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.sequence.asc())
        )
        res = await self._db.execute(stmt)
        return list(res.scalars().all())

    async def list_conversations(self, *, limit: int, offset: int, tenant_id: str) -> list[ConversationListRow]:
        stmt = (
            select(
                Conversation.id.label("conversation_id"),
                Conversation.created_at,
                Conversation.updated_at,
                func.count(Message.id).label("message_count"),
            )
            .select_from(Conversation)
            .where(Conversation.tenant_id == tenant_id)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .group_by(Conversation.id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self._db.execute(stmt)
        rows = res.all()

        return [
            ConversationListRow(
                conversation_id=r.conversation_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
                message_count=int(r.message_count or 0),
            )
            for r in rows
        ]
