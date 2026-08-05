"""ORQ-23 AC3: cross-tenant regression test on the retrieval capability
(pattern from ORQ-18.2 Test 4). Exercised at the `RetrievalPipeline` +
`PgVectorStore` layer against a real Postgres/RLS -- the same isolation
boundary the new `/rag/retrieve` endpoint depends on via `get_rag_db`
(app/infra/db/session.py), which this test does not re-derive.

Skipped unless RAG_TEST_DATABASE_URL (privileged, for seeding) and
RAG_TEST_DATABASE_URL_APP (the rag_app role) are both set -- same convention
as tests/core/test_rag_rls.py.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.domain.provider import ProviderInput, ProviderResult
from app.core.domain.reranker import RankedDocument, RerankRequest
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.providers.pgvector_store import PgVectorStore
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker

pytestmark = pytest.mark.postgres

_DUMMY_EMBEDDING = [0.001] * 1536


class _NoRewriteProvider:
    async def generate(self, input: ProviderInput) -> ProviderResult:
        # Echo the user query back unchanged -- keeps hybrid_search's
        # keyword match deterministic for this isolation test.
        return ProviderResult(content=input.messages[-1].content, provider="stub", model_version="v1", prompt_version="v1")


class _IdentityEmbedding:
    async def embed_one(self, text: str):
        return _DUMMY_EMBEDDING

    async def embed_many(self, texts):
        raise NotImplementedError


class _PassthroughReranker:
    async def rerank(self, request: RerankRequest):
        return [RankedDocument(index=i, rank=i + 1) for i in range(len(request.documents))]


def _privileged_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _app_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL_APP")
    if not url:
        pytest.skip("RAG_TEST_DATABASE_URL_APP not set")
    return url


@pytest.fixture
async def seeded_tenants():
    engine = create_async_engine(_privileged_url())
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as conn:
            for doc_id, tenant, path in [(doc_a, "tenant-a", "a.md"), (doc_b, "tenant-b", "b.md")]:
                await conn.execute(
                    text(
                        "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type) "
                        "VALUES (:id, :tenant_id, :path, :hash, 'markdown')"
                    ),
                    {"id": doc_id, "tenant_id": tenant, "path": path, "hash": f"hash-{tenant}"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO chunks (id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                        "VALUES (gen_random_uuid(), :doc_id, :tenant_id, 0, :text, CAST(:embedding AS vector), to_tsvector('english', :text))"
                    ),
                    {
                        "doc_id": doc_id,
                        "tenant_id": tenant,
                        "text": f"needle for {tenant}",
                        "embedding": "[" + ",".join(str(v) for v in _DUMMY_EMBEDDING) + "]",
                    },
                )
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents WHERE tenant_id IN ('tenant-a', 'tenant-b')"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_retrieval_pipeline_never_returns_other_tenants_chunks(seeded_tenants) -> None:
    sessionmaker = build_rag_sessionmaker(_app_url())

    with tenant_scope("tenant-a"):
        async with sessionmaker() as session:
            pipeline = RetrievalPipeline(
                provider=_NoRewriteProvider(),
                embedding=_IdentityEmbedding(),
                vector_store=PgVectorStore(session),
                reranker=_PassthroughReranker(),
                min_reranked_results=1,
            )
            result = await pipeline.retrieve(request_id=uuid.uuid4(), query="needle")

    texts = [ranked.chunk.text for ranked in result.chunks]
    assert any("tenant-a" in t for t in texts)
    assert not any("tenant-b" in t for t in texts)
