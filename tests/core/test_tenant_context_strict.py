"""ORQ-21 R1 (Execution Review): TenantScopedSession must fail closed when no
tenant was explicitly set, instead of silently operating as tenant "default".

Hermetic (sqlite) — get_tenant_id_strict() raises inside after_begin before
any SQL is sent, so this never needs a real Postgres connection to exercise
the failure mode; RLS-under-Postgres itself stays covered by
tests/core/test_rag_rls.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.http.middleware.tenant import (
    TenantContextError,
    get_tenant_id,
    get_tenant_id_strict,
    tenant_scope,
)
from app.infra.db.session import TenantScopedSession


def test_get_tenant_id_strict_raises_when_unset() -> None:
    with pytest.raises(TenantContextError):
        get_tenant_id_strict()


def test_get_tenant_id_lenient_still_defaults_when_unset() -> None:
    # Unchanged behaviour for HTTP/logging callers -- only the RAG session
    # path (get_tenant_id_strict) tightened.
    assert get_tenant_id() == "default"


def test_get_tenant_id_strict_returns_value_inside_tenant_scope() -> None:
    with tenant_scope("tenant-a"):
        assert get_tenant_id_strict() == "tenant-a"


@pytest.mark.asyncio
async def test_tenant_scoped_session_without_scope_fails_closed() -> None:
    # sqlite is fine for this half only: get_tenant_id_strict() raises inside
    # after_begin *before* the handler's `SELECT set_config(...)` (Postgres-only)
    # is ever sent, so no real Postgres dialect is needed to prove the fail-closed
    # path. The mirror case -- a scoped session successfully reaching that
    # Postgres-specific statement -- is covered against real Postgres in
    # tests/core/test_rag_rls.py, not here.
    #
    # Engine built directly (not via build_rag_sessionmaker, which doesn't
    # expose it) so it can be disposed explicitly -- otherwise aiosqlite's
    # non-daemon worker thread for the opened connection keeps the process
    # alive indefinitely after the test itself has already passed.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        sessionmaker = async_sessionmaker(
            bind=engine, sync_session_class=TenantScopedSession, expire_on_commit=False
        )
        with pytest.raises((TenantContextError, DBAPIError, StatementError)) as exc_info:
            async with sessionmaker() as session:
                await session.execute(text("SELECT 1"))
        assert "tenant_id context not set" in str(exc_info.value)
    finally:
        await engine.dispose()
