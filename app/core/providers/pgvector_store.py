from __future__ import annotations

import json
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain.vector_store import ChunkUpsert, RetrievedChunk, VectorStorePort

# Reciprocal Rank Fusion constant (standard default). Needs no score
# normalisation between the two incomparable scales — cosine distance and
# ts_rank — which is exactly why RRF, not a weighted sum, is used to fuse
# them (spec.md §Design decisions 6).
_RRF_K = 60

# Every ORDER BY below carries `id` as a final tiebreaker. RRF produces exact
# score ties by construction — a chunk found only by the semantic leg at rank r
# scores 1.0/(60+r), identical to a chunk found only by the keyword leg at the
# same rank — and ts_rank ties are the common case, not the edge case. Without
# the tiebreaker both the *membership* of each CTE (ORDER BY ... LIMIT) and the
# final ordering are left to the plan, so an autovacuum or a plan change can
# silently reorder results for an unchanged corpus and an unchanged query.
# `id` is a random UUID: arbitrary as a preference, but stable, which is all a
# tiebreaker has to be. It never reorders chunks with distinct scores
# (ORQ-26 Task 0, ADR-009).


class PgVectorStore(VectorStorePort):
    """
    pgvector adapter: cosine-distance semantic search + Postgres full-text
    keyword search (ts_rank over the application-written tsvector — not
    BM25), fused with Reciprocal Rank Fusion.

    Must be given a session already scoped to a tenant via the
    `app.tenant_id` GUC (app/infra/db/session.py TenantScopedSession) — this
    adapter issues no tenant_id filter itself; RLS on `documents`/`chunks`
    is the isolation control (ADR-006 §2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_chunks(self, chunks: Sequence[ChunkUpsert]) -> None:
        if not chunks:
            return
        for chunk in chunks:
            await self._session.execute(
                text(
                    """
                    INSERT INTO chunks
                        (id, document_id, tenant_id, ordinal, text, context,
                         embedding, search_vector, metadata)
                    VALUES
                        (gen_random_uuid(), :document_id, :tenant_id, :ordinal, :text, :context,
                         CAST(:embedding AS vector), to_tsvector('english', :search_text), CAST(:metadata AS jsonb))
                    ON CONFLICT (document_id, ordinal) DO UPDATE SET
                        text = EXCLUDED.text,
                        context = EXCLUDED.context,
                        embedding = EXCLUDED.embedding,
                        search_vector = EXCLUDED.search_vector,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    "document_id": chunk.document_id,
                    "tenant_id": chunk.tenant_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "context": chunk.context,
                    "embedding": _format_vector(chunk.embedding),
                    "search_text": chunk.search_text,
                    "metadata": json.dumps(chunk.metadata) if chunk.metadata is not None else None,
                },
            )

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top_k: int = 20,
    ) -> Sequence[RetrievedChunk]:
        result = await self._session.execute(
            text(
                """
                WITH semantic AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY embedding <=> CAST(:query_embedding AS vector), id) AS rank
                    FROM chunks
                    ORDER BY embedding <=> CAST(:query_embedding AS vector), id
                    LIMIT :top_k
                ),
                keyword AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query_text)) DESC, id) AS rank
                    FROM chunks
                    WHERE search_vector @@ plainto_tsquery('english', :query_text)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query_text)) DESC, id
                    LIMIT :top_k
                ),
                fused AS (
                    SELECT
                        COALESCE(semantic.id, keyword.id) AS id,
                        COALESCE(semantic.document_id, keyword.document_id) AS document_id,
                        COALESCE(semantic.text, keyword.text) AS text,
                        COALESCE(semantic.metadata, keyword.metadata) AS metadata,
                        COALESCE(1.0 / (:rrf_k + semantic.rank), 0.0)
                            + COALESCE(1.0 / (:rrf_k + keyword.rank), 0.0) AS score
                    FROM semantic
                    FULL OUTER JOIN keyword ON semantic.id = keyword.id
                )
                SELECT id, document_id, text, metadata, score
                FROM fused
                ORDER BY score DESC, id
                LIMIT :top_k
                """
            ),
            {
                "query_embedding": _format_vector(query_embedding),
                "query_text": query_text,
                "top_k": top_k,
                "rrf_k": _RRF_K,
            },
        )
        return [
            RetrievedChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                text=row.text,
                score=row.score,
                metadata=row.metadata,
            )
            for row in result
        ]


def _format_vector(embedding: Sequence[float]) -> str:
    # pgvector's text input format: "[v1,v2,...]". Passed as a plain string
    # bind parameter; the column's `vector` type cast happens server-side.
    return "[" + ",".join(str(float(v)) for v in embedding) + "]"
