from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.http.middleware.tenant import get_tenant_id
from app.infra.db.session import get_db
from app.schemas.conversations import (
    ConversationDetailOut,
    ConversationListItemOut,
    ConversationListOut,
    ConversationMessageOut,
)
from app.services.conversation_query_service import ConversationQueryService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 100)


def _clamp_offset(offset: int) -> int:
    return max(offset, 0)


@router.get("", response_model=ConversationListOut)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, description="default 20, max 100"),
    offset: int = Query(0, description="default 0"),
) -> ConversationListOut:
    qs = ConversationQueryService(db)
    tenant_id = get_tenant_id()

    limit_c = _clamp_limit(limit)
    offset_c = _clamp_offset(offset)

    rows = await qs.list_conversations(limit=limit_c, offset=offset_c, tenant_id=tenant_id)

    return ConversationListOut(
        items=[
            ConversationListItemOut(
                conversation_id=r.conversation_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
                message_count=r.message_count,
            )
            for r in rows
        ],
        limit=limit_c,
        offset=offset_c,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation_detail(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailOut:
    qs = ConversationQueryService(db)
    tenant_id = get_tenant_id()

    convo = await qs.get_conversation(conversation_id, tenant_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await qs.list_messages_for_conversation(conversation_id, tenant_id)

    return ConversationDetailOut(
        id=convo.id,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
        messages=[
            ConversationMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )