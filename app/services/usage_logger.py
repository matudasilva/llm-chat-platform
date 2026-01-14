# app/services/usage_logger.py
from __future__ import annotations

import uuid
from typing import Optional

from app.infra.db.session import SessionLocal
from app.models.usage_event import UsageEvent


async def log_usage_event(
    *,
    provider: str,
    model_version: str,
    prompt_version: str,
    status: str,
    request_id: Optional[uuid.UUID] = None,
    conversation_id: Optional[uuid.UUID] = None,
    message_id: Optional[uuid.UUID] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    async with SessionLocal() as s:
        ev = UsageEvent(
            id=uuid.uuid4(),
            provider=provider,
            model_version=model_version,
            prompt_version=prompt_version,
            status=status,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        s.add(ev)
        await s.commit()
