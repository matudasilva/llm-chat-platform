from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChunkUpsert:
    document_id: UUID
    tenant_id: str
    ordinal: int
    text: str
    embedding: Sequence[float]
    search_text: str
    context: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    score: float
    metadata: dict[str, Any] | None = None


class VectorStorePort(Protocol):
    """
    ORQ-21 / ADR-006: hybrid retrieval over the pgvector-backed corpus.
    Tenant isolation is enforced by Postgres RLS on the connection this
    adapter is given, not by an explicit tenant_id filter here.
    """

    async def upsert_chunks(self, chunks: Sequence[ChunkUpsert]) -> None:
        ...

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top_k: int = 20,
    ) -> Sequence[RetrievedChunk]:
        ...
