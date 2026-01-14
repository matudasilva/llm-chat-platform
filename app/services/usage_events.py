import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage_event import UsageEvent

async def log_usage_event(
    db: AsyncSession,
    *,
    provider: str,
    model_version: str,
    prompt_version: str,
    conversation_id: Optional[uuid.UUID] = None,
    message_id: Optional[uuid.UUID] = None,
    request_id: Optional[uuid.UUID] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
) -> uuid.UUID:
    ev_id = uuid.uuid4()
    ev = UsageEvent(
        id=ev_id,
        conversation_id=conversation_id,
        message_id=message_id,
        request_id=request_id,
        provider=provider,
        model_version=model_version,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        status=status,
        error_message=error_message,
    )
    db.add(ev)
    await db.commit()
    return ev_id
