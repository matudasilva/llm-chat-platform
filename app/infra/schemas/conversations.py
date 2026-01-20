from datetime import datetime
from uuid import UUID
from typing import Optional, Literal, List

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: List[MessageOut]
