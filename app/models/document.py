from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base


class Document(Base):
    """A source unit ingested into the RAG corpus (spec.md §Design decisions 3)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # ORQ-21 ADR-006 §5/§6: which ingestion mode produced this document's chunks
    # ("plain" or "contextualized"), so a document is re-indexed rather than
    # skipped by content_hash alone when the mode changes.
    indexing_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="plain",
    )

    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_documents_tenant_id", "tenant_id"),
        Index(
            "ux_documents_tenant_source_hash",
            "tenant_id",
            "source_path",
            "content_hash",
            "indexing_mode",
            unique=True,
        ),
    )
