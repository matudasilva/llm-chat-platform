from __future__ import annotations

from typing import Literal, List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.infra.schemas.conversations import ConversationSummary, MessageOut, ConversationDetail

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=List[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    order: Literal["asc", "desc"] = Query("desc"),
) -> List[ConversationSummary]:
    order_by = (Conversation.created_at.asc(), Conversation.id.asc())
    if order == "desc":
        order_by = (Conversation.created_at.desc(), Conversation.id.desc())

    stmt = (
        select(Conversation)
        .order_by(*order_by)
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_detail(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    # 1) Conversation
    convo_stmt = select(Conversation).where(Conversation.id == conversation_id)
    convo_res = await db.execute(convo_stmt)
    conversation = convo_res.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2) Messages (orden determinista)
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    msg_res = await db.execute(msg_stmt)
    messages = msg_res.scalars().all()

    return ConversationDetail(
        conversation=conversation,
        messages=messages,
    )
