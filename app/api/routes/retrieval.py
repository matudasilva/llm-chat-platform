from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain.provider_factory import build_provider
from app.core.domain.retrieval_factory import build_embedding_provider, build_reranker
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.providers.pgvector_store import PgVectorStore
from app.core.settings import settings
from app.http.middleware.tenant import get_tenant_id
from app.infra.db.session import get_rag_db
from app.schemas.retrieval import RetrievedChunkOut, RetrieveRequest, RetrieveResponse

# ORQ-23 spec.md §Design decisions 2: POST because the query travels in the
# body alongside optional overrides (top_n) that would otherwise need to
# grow as querystring-only parameters -- operator-approved 2026-08-05.
router = APIRouter(prefix="/rag", tags=["retrieval"])


def require_retrieval_pipeline_enabled() -> None:
    if not settings.retrieval_pipeline_enabled:
        raise HTTPException(status_code=403, detail="retrieval pipeline is disabled")


def get_retrieval_pipeline(db: AsyncSession = Depends(get_rag_db)) -> RetrievalPipeline:
    # db is a TenantScopedSession bound to DATABASE_URL_APP (the unprivileged
    # rag_app role) -- RLS enforces tenant isolation on the corpus itself
    # (ADR-006 §2), unchanged from ORQ-21. Read-only: no write path is added.
    return RetrievalPipeline(
        provider=build_provider(),
        embedding=build_embedding_provider(),
        vector_store=PgVectorStore(db),
        reranker=build_reranker(),
        min_reranked_results=settings.retrieval_pipeline_min_reranked_results,
    )


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    _enabled: None = Depends(require_retrieval_pipeline_enabled),
    pipeline: RetrievalPipeline = Depends(get_retrieval_pipeline),
) -> RetrieveResponse:
    # Read only, for telemetry/parity with conversations.py -- tenant
    # isolation itself is enforced by RLS on the get_rag_db session above,
    # not by an explicit filter here (spec.md §Risks R3).
    get_tenant_id()

    result = await pipeline.retrieve(
        request_id=uuid4(),
        query=body.query,
        top_n=body.top_n,
    )

    return RetrieveResponse(
        query=result.query,
        rewritten_query=result.rewritten_query,
        chunks=[
            RetrievedChunkOut(
                chunk_id=ranked.chunk.chunk_id,
                document_id=ranked.chunk.document_id,
                text=ranked.chunk.text,
                rank=ranked.rank,
            )
            for ranked in result.chunks
        ],
        fallback_triggered=result.fallback_triggered,
        evaluator_triggered=result.evaluator_triggered,
        evaluator_verdict=result.evaluator_verdict,
    )
