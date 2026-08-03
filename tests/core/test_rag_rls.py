"""ORQ-21 AC3 / AC8: RLS is enforced, not merely declared, and WITH CHECK is
load-bearing, not decorative.

Skipped unless RAG_TEST_DATABASE_URL (privileged, for seeding) and
RAG_TEST_DATABASE_URL_APP (the rag_app role) are both set -- see pytest.ini's
`postgres` marker and tests/conftest.py's skip predicate, which gates on the
former; this module additionally requires the latter.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.providers.pgvector_store import PgVectorStore
from app.core.domain.vector_store import ChunkUpsert
from app.http.middleware.tenant import TenantContextError, tenant_scope
from app.infra.db.session import build_rag_sessionmaker

pytestmark = pytest.mark.postgres

_DUMMY_EMBEDDING = [0.001] * 1536


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
    """Seeds one document + one chunk each for tenant-a and tenant-b, as the
    privileged role (RLS does not apply to it -- this is the seeding
    exception, not a claim that the owner role is a safe query path)."""
    engine = create_async_engine(_privileged_url())
    doc_a, doc_b, chunk_a_id, chunk_b_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
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
            for chunk_id, doc_id, tenant in [(chunk_a_id, doc_a, "tenant-a"), (chunk_b_id, doc_b, "tenant-b")]:
                await conn.execute(
                    text(
                        "INSERT INTO chunks (id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                        "VALUES (:id, :doc_id, :tenant_id, 0, :text, CAST(:embedding AS vector), to_tsvector('english', :text))"
                    ),
                    {
                        "id": chunk_id,
                        "doc_id": doc_id,
                        "tenant_id": tenant,
                        "text": f"chunk for {tenant}",
                        "embedding": "[" + ",".join(str(v) for v in _DUMMY_EMBEDDING) + "]",
                    },
                )
        yield {"chunk_a_id": chunk_a_id, "chunk_b_id": chunk_b_id, "doc_a_id": doc_a, "doc_b_id": doc_b}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents WHERE tenant_id IN ('tenant-a', 'tenant-b')"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_a_sees_none_of_tenant_b_rows(seeded_tenants) -> None:
    sm = build_rag_sessionmaker(_app_url())
    with tenant_scope("tenant-a"):
        async with sm() as session:
            total = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
            foreign = (
                await session.execute(text("SELECT count(*) FROM documents WHERE tenant_id = 'tenant-b'"))
            ).scalar_one()
    assert total > 0
    assert foreign == 0


@pytest.mark.asyncio
async def test_no_context_set_returns_zero_rows(seeded_tenants) -> None:
    # Deliberately bypasses TenantScopedSession -- a raw connection that never
    # runs set_config('app.tenant_id', ...) at all, so current_setting(..., true)
    # is NULL. This is the actual "no context set" case: TenantScopedSession's
    # after_begin always sets at least the "default" tenant, so reaching a
    # truly-NULL GUC requires a connection that skips it entirely -- exactly
    # the failure mode this test guards against for any future code path.
    engine = create_async_engine(_app_url())
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    finally:
        await engine.dispose()
    assert rows == 0


@pytest.mark.asyncio
async def test_direct_id_access_does_not_bypass_policy(seeded_tenants) -> None:
    sm = build_rag_sessionmaker(_app_url())
    with tenant_scope("tenant-a"):
        async with sm() as session:
            result = await session.execute(
                text("SELECT * FROM chunks WHERE id = :id"),
                {"id": seeded_tenants["chunk_b_id"]},
            )
            assert result.first() is None


@pytest.mark.asyncio
async def test_with_check_rejects_foreign_tenant_insert(seeded_tenants) -> None:
    sm = build_rag_sessionmaker(_app_url())
    with tenant_scope("tenant-a"):
        async with sm() as session:
            store = PgVectorStore(session)
            with pytest.raises(DBAPIError, match="row-level security"):
                await store.upsert_chunks(
                    [
                        ChunkUpsert(
                            document_id=seeded_tenants["doc_b_id"],
                            tenant_id="tenant-b",
                            ordinal=99,
                            text="attempted foreign-tenant insert",
                            embedding=_DUMMY_EMBEDDING,
                            search_text="attempted foreign-tenant insert",
                        )
                    ]
                )
            await session.rollback()


@pytest.mark.asyncio
async def test_tenant_scoped_session_without_scope_fails_closed_on_real_postgres() -> None:
    """ORQ-21 R1 (Execution Review): no fallback to tenant "default" against a
    real Postgres either -- get_tenant_id_strict() must raise inside
    after_begin before the transaction reaches Postgres at all, not just in
    the sqlite-based unit test (tests/core/test_tenant_context_strict.py)."""
    sm = build_rag_sessionmaker(_app_url())
    with pytest.raises(TenantContextError, match="tenant_id context not set"):
        async with sm() as session:
            await session.execute(text("SELECT 1"))
