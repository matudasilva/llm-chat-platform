from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class ChatStatus(str, Enum):
    success = "success"
    error = "error"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conversation_id: Optional[UUID] = Field(
        default=None,
        description="Existing conversation identifier. If omitted, a new conversation is created.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=20_000,
        description="User message content.",
    )


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID = Field(..., description="Unique request identifier for tracing.")
    conversation_id: UUID = Field(..., description="Conversation identifier for the chat session.")

    user_message_id: Optional[UUID] = Field(
        default=None,
        description="Persisted user message id (when write-path is enabled).",
    )
    assistant_message_id: Optional[UUID] = Field(
        default=None,
        description="Persisted assistant message id (when write-path is enabled).",
    )

    assistant_content: Optional[str] = Field(
        default=None,
        description="Assistant response text (null on error).",
    )

    status: ChatStatus = Field(..., description="success or error")

    error_message: Optional[str] = Field(
        default=None,
        max_length=2_000,
        description="Error details suitable for logs/UI (kept short).",
    )
