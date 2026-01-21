# app/infra/schemas/usage_events.py
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: Optional[UUID] = None
    message_id: Optional[UUID] = None

    provider: str
    model_version: str
    prompt_version: str

    request_id: Optional[UUID] = None  # nullable en DB
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None

    status: Optional[str] = None        # nullable en DB
    error_message: Optional[str] = None

    timestamp: datetime
