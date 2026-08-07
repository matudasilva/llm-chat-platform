from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.http.middleware.tenant import get_tenant_id
from app.infra.db.session import get_db
from app.models.message import Message, MessageRole
from app.models.usage_event import UsageEvent
from app.schemas.chat import ChatFeedbackRequest, ChatFeedbackResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.put(
    "/messages/{message_id}/feedback",
    response_model=ChatFeedbackResponse,
)
async def put_chat_feedback(
    message_id: UUID,
    body: ChatFeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatFeedbackResponse:
    tenant_id = get_tenant_id()
    result = await db.execute(
        select(UsageEvent)
        .join(Message, UsageEvent.message_id == Message.id)
        .where(
            UsageEvent.message_id == message_id,
            UsageEvent.status == "success",
            Message.role == MessageRole.assistant,
            Message.tenant_id == tenant_id,
        )
        .order_by(UsageEvent.timestamp.desc(), UsageEvent.id.desc())
    )
    events = list(result.scalars().all())
    if not events:
        await db.rollback()
        raise HTTPException(status_code=404, detail="message_id not found")
    if len(events) > 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="feedback target is ambiguous")

    event = events[0]
    if event.feedback == body.rating and event.feedback_updated_at is not None:
        feedback_updated_at = event.feedback_updated_at
        await db.rollback()
        return ChatFeedbackResponse(
            message_id=message_id,
            rating=body.rating,
            feedback_updated_at=feedback_updated_at,
        )

    event.feedback = body.rating
    event.feedback_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return ChatFeedbackResponse(
        message_id=message_id,
        rating=body.rating,
        feedback_updated_at=event.feedback_updated_at,
    )
