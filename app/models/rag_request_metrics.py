"""ORQ-37 §Diseño 6: per-request RAG pipeline metrics.

A sibling of `UsageEvent`, correlated ADVISORILY on `request_id` -- never
authoritatively. `UsageEvent` has no `request_instance_id` and this ORQ does
not add one; that table carries its own open debt and is not refactored here
(invariant 9). Every metric this ORQ measures is derivable from this table
alone (AC25) -- the join is for cross-reference only.

Identity is server-side: `request_instance_id` is the `uuid4` minted in
`RequestContextMiddleware` (§Diseño 3), unique by construction, and the column
carrying the uniqueness constraint. `request_id` is retained as ordinary
correlation metadata -- indexed, NOT unique -- because it is accepted verbatim
from the client and a replayed header must not corrupt per-request cost
attribution or turn a uniqueness violation into a swallowed best-effort
failure (AC25).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base


class RagRequestMetrics(Base):
    __tablename__ = "rag_request_metrics"
    __table_args__ = (
        Index("ix_rag_request_metrics_request_id", "request_id"),
        Index("ix_rag_request_metrics_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    request_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    mode: Mapped[str | None] = mapped_column(String(1), nullable=True)  # 'A' / 'B'

    retrieval_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    memory_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)

    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ebm25_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    rewrite_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieve_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rerank_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluate_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generate_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fallback_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    history_truncated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ebm25_selected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    history_row_cap_reached: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
