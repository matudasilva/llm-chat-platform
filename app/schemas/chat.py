from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.settings import settings


class ChatStatus(str, Enum):
    success = "success"
    error = "error"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stream: bool = False
    model_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    conversation_id: Optional[UUID] = Field(
        default=None,
        description="Conversation identifier (null on early error).",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=settings.max_message_chars,
        description="User message content.",
    )

    @field_validator("model_id", mode="before")
    @classmethod
    def validate_model_id(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value)):
            raise ValueError("invalid model ID")
        return value

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        # Defensive: even with str_strip_whitespace, keep this explicit.
        if not v or not v.strip():
            raise ValueError("message must not be blank")
        return v


class RagSourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation: str
    document_id: UUID
    chunk_id: UUID
    rank: int


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID = Field(..., description="Unique request identifier for tracing.")
    conversation_id: UUID = Field(..., description="Conversation identifier for the chat session.")
    stream: bool = False

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

    sources: list[RagSourceOut] = Field(default_factory=list)

    status: ChatStatus = Field(..., description="success or error")

    error_message: Optional[str] = Field(
        default=None,
        max_length=settings.max_error_message_chars,
        description="Error details suitable for logs/UI (kept short).",
    )


class ChatFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]


class ChatFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    rating: Literal["up", "down"]
    feedback_updated_at: datetime
