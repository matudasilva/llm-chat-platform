# app/infra/db/session.py
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session as SyncSession, SessionTransaction

from app.core.settings import settings
from app.http.middleware.tenant import get_tenant_id_strict

logger = logging.getLogger(__name__)

_ENGINE_KEY = "db_engine"
_SESSIONMAKER_KEY = "db_sessionmaker"
_RAG_ENGINE_KEY = "rag_db_engine"
_RAG_SESSIONMAKER_KEY = "rag_db_sessionmaker"
_OPS_ENGINE_KEY = "ops_db_engine"
_OPS_SESSIONMAKER_KEY = "ops_db_sessionmaker"


class TenantScopedSession(SyncSession):
    """
    Sync Session subclass carrying the tenant-GUC `after_begin` handler
    (spec.md §Design decisions 5, ORQ-21).

    Registered via `sync_session_class=` on `async_sessionmaker` — the
    `after_begin` event is not registrable on `async_sessionmaker` itself
    (`InvalidRequestError: No such event 'after_begin'`), and registering it
    on plain `orm.Session` would apply process-wide to every session in the
    app, including the non-RAG one used by `/chat`. Used by both the FastAPI
    app (via `init_db`) and the offline ingestion script (Task 5), so both
    reuse the identical GUC-setting behaviour against `DATABASE_URL_APP`.
    """


@event.listens_for(TenantScopedSession, "after_begin")
def _set_tenant_guc(session: SyncSession, transaction: SessionTransaction, connection: Connection) -> None:
    # Synchronous handler over the sync Connection SQLAlchemy hands to
    # `after_begin` even under the asyncio extension (greenlet-dispatched) —
    # an `async def` handler here would register silently and never be
    # awaited. Re-applied at the start of every transaction, regardless of
    # who began it: `set_config(..., true)` is transaction-local and would
    # otherwise vanish at the first commit. `set_config` (rather than
    # `SET LOCAL`) accepts a bind parameter, avoiding string interpolation of
    # the tenant id into SQL text.
    #
    # get_tenant_id_strict() (not get_tenant_id()) — raises TenantContextError
    # before this executes if nobody called tenant_scope()/TenantMiddleware
    # set the context, instead of silently defaulting to tenant "default"
    # (ORQ-21 R1).
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": get_tenant_id_strict()},
    )


def init_db(app) -> None:
    """
    Create engine + sessionmaker and store them on app.state.
    This MUST be called in FastAPI lifespan startup.
    """
    engine: AsyncEngine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    sessionmaker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    setattr(app.state, _ENGINE_KEY, engine)
    setattr(app.state, _SESSIONMAKER_KEY, sessionmaker)

    # RAG corpus (ORQ-21): a second engine/sessionmaker bound to the
    # unprivileged application role. Only created when DATABASE_URL_APP is
    # configured — never derived from settings.database_url, which would
    # silently reconnect as the superuser and make every RLS policy inert
    # (spec.md §Design decisions 4).
    if settings.database_url_app:
        rag_engine: AsyncEngine = create_async_engine(
            settings.database_url_app,
            pool_pre_ping=True,
        )
        rag_sessionmaker = async_sessionmaker(
            bind=rag_engine,
            class_=AsyncSession,
            sync_session_class=TenantScopedSession,
            expire_on_commit=False,
        )
        setattr(app.state, _RAG_ENGINE_KEY, rag_engine)
        setattr(app.state, _RAG_SESSIONMAKER_KEY, rag_sessionmaker)
    else:
        setattr(app.state, _RAG_ENGINE_KEY, None)
        setattr(app.state, _RAG_SESSIONMAKER_KEY, None)

    # Operational path (ORQ-37 §Diseño 7): a THIRD engine and pool, bound to
    # the least-privilege `database_url_ops` role. Its own engine, not a
    # sessionmaker over an existing one, for two independent reasons:
    #
    #   * credential — `database_url_app` cannot read conversations/messages
    #     at all, and `database_url` is over-privileged for a read path;
    #   * pool — sharing the primary pool would double per-request concurrency
    #     on the pool the atomic `/chat` write needs, converting a best-effort
    #     read into a write-path failure. Neither engine sets
    #     `pool_size`/`max_overflow`, so the isolation IS the mitigation.
    #
    # No `TenantScopedSession` here: §Diseño 7 introduces no RLS on
    # `conversations`/`messages` (that debt stays ADR-004 §5's), tenant scoping
    # is the query service's explicit WHERE, and the GUC handler would raise
    # `TenantContextError` off-route where this session is legitimately used.
    if settings.database_url_ops:
        ops_engine: AsyncEngine = create_async_engine(
            settings.database_url_ops,
            pool_pre_ping=True,
        )
        ops_sessionmaker = async_sessionmaker(
            bind=ops_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        setattr(app.state, _OPS_ENGINE_KEY, ops_engine)
        setattr(app.state, _OPS_SESSIONMAKER_KEY, ops_sessionmaker)
    else:
        setattr(app.state, _OPS_ENGINE_KEY, None)
        setattr(app.state, _OPS_SESSIONMAKER_KEY, None)


async def close_db(app) -> None:
    """
    Dispose engine on shutdown to avoid event-loop / connection leaks in tests.
    """
    engine: AsyncEngine | None = getattr(app.state, _ENGINE_KEY, None)
    if engine is not None:
        await engine.dispose()

    rag_engine: AsyncEngine | None = getattr(app.state, _RAG_ENGINE_KEY, None)
    if rag_engine is not None:
        await rag_engine.dispose()

    # AC9: the operational engine is disposed too. An undisposed third pool
    # leaks connections across the lifespan boundary exactly as the other two
    # would.
    ops_engine: AsyncEngine | None = getattr(app.state, _OPS_ENGINE_KEY, None)
    if ops_engine is not None:
        await ops_engine.dispose()


def _get_sessionmaker_from_app(app) -> async_sessionmaker[AsyncSession]:
    sm = getattr(app.state, _SESSIONMAKER_KEY, None)
    if sm is None:
        raise RuntimeError("DB is not initialized. Did you forget to call init_db(app) in lifespan?")
    return sm


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = _get_sessionmaker_from_app(request.app)
    async with SessionLocal() as session:
        yield session


async def get_rag_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """RAG-corpus session, bound to DATABASE_URL_APP (the unprivileged role)."""
    sm = getattr(request.app.state, _RAG_SESSIONMAKER_KEY, None)
    if sm is None:
        raise RuntimeError(
            "RAG DB is not configured. Set DATABASE_URL_APP before use."
        )
    async with sm() as session:
        yield session


@asynccontextmanager
async def short_lived_rag_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Own and close a RAG session before `/chat` enters its write transaction."""
    sm = getattr(request.app.state, _RAG_SESSIONMAKER_KEY, None)
    if sm is None:
        raise RuntimeError("RAG DB is not configured. Set DATABASE_URL_APP before use.")
    async with sm() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


class OperationalDatabaseNotConfigured(RuntimeError):
    """`DATABASE_URL_OPS` is unset, so no operational engine exists.

    A distinct type rather than a bare ``RuntimeError`` so callers can tell
    "not configured" from "configured and broken". The two deserve opposite
    treatment: the first is the shipped inert default, the second is a fault.
    """


def get_history_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """The overridable seam of §Diseño 7.

    `tests/conftest.py` pins `DATABASE_URL="sqlite+aiosqlite:///:memory:"` and
    lets the real lifespan run. A second engine on that URL is a **separate,
    schema-less** in-memory database, so every hermetic history read would fail
    and the never-raising dependency above it would swallow the failure into
    empty history: the whole of Gate B1 could go green with the feature dead.
    AC28 exists to make that impossible — "a seeded conversation yields
    NON-empty history through the shipped dependency".

    **Substitution happens through `app.state`, not `dependency_overrides`.**
    This function reads `request.app.state.ops_db_sessionmaker`, which the
    lifespan populates; a harness substitutes a seeded database by setting
    that attribute. `tests/api/test_ac28_shipped_dependency.py` drives the
    shipped dependency that way, end to end, over a seeded database built from
    the real models.

    **It is deliberately NOT declared as a FastAPI dependency** (H8,
    2026-09-11). An earlier version of this docstring said it was "a FastAPI
    dependency on purpose"; that was never true of production, where both
    callers invoke it directly (`app/api/deps.py`, `app/api/routes/chat.py`),
    and `Depends(get_history_sessionmaker)` appeared only inside test-only
    routes. Making it one would move the `OperationalDatabaseNotConfigured`
    raise below into dependency resolution, before any handler body — and
    `DATABASE_URL_OPS` is empty in the shipped default, so the default
    configuration would answer 500. That breaks invariant 7 (the streaming
    path must answer an SSE `error` frame, never a 500) and AC13's
    never-raises contract, both of which the current direct call preserves by
    letting the raise land inside `get_chat_memory_context`'s own degradation
    boundary.
    """
    sm = getattr(request.app.state, _OPS_SESSIONMAKER_KEY, None)
    if sm is None:
        raise OperationalDatabaseNotConfigured(
            "Operational DB is not configured. Set DATABASE_URL_OPS before use."
        )
    return sm


@asynccontextmanager
async def short_lived_history_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Own and close a history session BEFORE `/chat` enters its write transaction.

    Takes the sessionmaker rather than the `Request` that
    `short_lived_rag_session` takes: the resolution step is
    `get_history_sessionmaker` above, and keeping the two separate is what
    makes the seam overridable and this context manager testable without an
    ASGI request at all.

    The `finally` rollback matters even on a read-only path — SQLAlchemy opens
    an implicit transaction on first execute, and an idle-in-transaction
    connection returned to the pool holds a snapshot open.
    """
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


def build_rag_sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    """
    Standalone RAG sessionmaker for callers outside the FastAPI lifespan —
    the offline ingestion script (spec.md §Design decisions 8), which never
    runs `init_db` and must still get the tenant-GUC `after_begin` behaviour.
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        sync_session_class=TenantScopedSession,
        expire_on_commit=False,
    )


async def test_db_connection(app, retries: int = 10, delay: float = 2.0) -> None:
    """
    Optional: use the app-bound engine (not a module-global engine).
    """
    engine: AsyncEngine | None = getattr(app.state, _ENGINE_KEY, None)
    if engine is None:
        raise RuntimeError("DB engine not initialized")

    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return
        except OperationalError:
            logger.warning(
                "Database not ready (attempt %s/%s). Retrying in %.1fs...",
                attempt,
                retries,
                delay,
            )
            if attempt == retries:
                logger.error("Database connection failed after retries")
                raise
            await asyncio.sleep(delay)
