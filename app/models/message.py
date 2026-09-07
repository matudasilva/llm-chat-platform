from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base
from app.models.conversation import Conversation



class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"),
        nullable=False,
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="default",
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
        # ORQ-37 T12 / AC15: supports the operational history read's
        # `ORDER BY sequence DESC LIMIT n` (`d29e6a1f4c87`). Declared here too
        # so ORM metadata and the migration chain agree -- an autogenerate
        # diff against a model missing this would otherwise propose dropping
        # it.
        Index("ix_messages_conversation_id_sequence", "conversation_id", "sequence"),
    )
