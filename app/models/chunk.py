from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base

EMBEDDING_DIMENSIONS = 1536  # ADR-006 §1 — corpus-level constant, not per tenant.


class Chunk(Base):
    """A retrievable unit of a Document (spec.md §Design decisions 3)."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    # Original chunk text, never the contextualized form — this is what feeds
    # the augmented prompt (ADR-006 §6).
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Populated only when ingested with --contextualize; the situating
    # sentences prepended before embedding. NULL in plain mode.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS),
        nullable=False,
    )

    # Application-written, not a generated column (ADR-006 §5): the source
    # expression differs by indexing mode (text vs. context || text).
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)

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

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_tenant_id", "tenant_id"),
        Index("ix_chunks_document_id", "document_id"),
        Index(
            "ux_chunks_document_ordinal",
            "document_id",
            "ordinal",
            unique=True,
        ),
    )
