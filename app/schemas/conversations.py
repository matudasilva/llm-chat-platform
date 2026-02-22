# app/schemas/conversations.py
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Role = Literal["user", "assistant", "system"]


class ConversationMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Role
    content: str
    created_at: datetime


class ConversationDetailOut(BaseModel):
    conversation_id: UUID = Field(..., alias="id")
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageOut]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ConversationListItemOut(BaseModel):
    conversation_id: UUID
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationListOut(BaseModel):
    items: list[ConversationListItemOut]
    limit: int
    offset: int