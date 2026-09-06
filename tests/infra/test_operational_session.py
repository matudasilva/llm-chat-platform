"""ORQ-37 T7 (Gate B1 half) — the operational session, its engine and its seam.

Covers **AC9's history-read half** (engine identity and disposal) and **AC28**
(a seeded conversation yields NON-empty history on the hermetic path).

AC28 is the criterion that exists because the harness would otherwise hide the
feature: `tests/conftest.py` pins `DATABASE_URL="sqlite+aiosqlite:///:memory:"`
and lets the real lifespan run, so a second engine on that URL is a separate,
schema-less database. Every history read would fail, the best-effort layer
above would swallow it into empty history, and Gate B1 could go green with the
feature dead. Nothing here is proven by a double: AC28 runs against a real
engine holding a real schema with real rows.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from app.infra.db import session as session_module
from app.infra.db.base import Base
from app.infra.db.session import (
    OperationalDatabaseNotConfigured,
    close_db,
    get_history_sessionmaker,
    init_db,
    short_lived_history_session,
)
from app.models.conversation import Conversation  # noqa: F401  (registers the table)
from app.models.message import Message, MessageRole
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService

pytestmark = pytest.mark.asyncio

PRIMARY_URL = "sqlite+aiosqlite:///:memory:"
RAG_URL = "sqlite+aiosqlite:///file:ac9-rag?mode=memory&cache=shared&uri=true"
OPS_URL = "sqlite+aiosqlite:///file:ac9-ops?mode=memory&cache=shared&uri=true"

TENANT = "acme"


@compiles(JSONB, "sqlite")
def _jsonb_renders_as_json_on_sqlite(type_, compiler, **kw) -> str:
    """DDL shim so `conversations` can be CREATEd on the hermetic engine.

    `Conversation.metadata_` is `JSONB`, which the SQLite compiler cannot
    render. Production never compiles JSONB for SQLite — the application runs
    on PostgreSQL — so this affects the test path only. It is a *rendering*
    shim, not a schema redefinition: the tables still come from the real
    `Base.metadata`, which is what makes a model/schema drift break AC28
    instead of silently passing.
    """
    return "JSON"


def _settings(*, ops: str | None, app_url: str | None = RAG_URL) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=PRIMARY_URL,
        database_url_app=app_url,
        database_url_ops=ops,
    )


def _app() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


# --- AC9: engine identity --------------------------------------------------


async def test_ops_engine_binds_to_database_url_ops(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        engine = getattr(app.state, session_module._OPS_ENGINE_KEY)
        assert engine is not None
        # Compared field by field, not as a string: SQLAlchemy normalizes the
        # query-parameter order, so a string equality would fail for a reason
        # that has nothing to do with which database the engine points at.
        expected = make_url(OPS_URL)
        assert engine.url.drivername == expected.drivername
        assert engine.url.database == expected.database
        assert dict(engine.url.query) == dict(expected.query)
    finally:
        await close_db(app)


async def test_ops_engine_is_never_the_primary_engine(monkeypatch) -> None:
    # AC9's "never from settings.database_url": asserted on the ENGINE, not on
    # the setting, because the failure this guards against is a future edit
    # that binds the operational sessionmaker to the primary engine while
    # leaving the setting untouched.
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        primary = getattr(app.state, session_module._ENGINE_KEY)
        ops = getattr(app.state, session_module._OPS_ENGINE_KEY)
        assert ops is not primary
        assert ops.url != primary.url
    finally:
        await close_db(app)


async def test_ops_engine_is_never_the_rag_engine(monkeypatch) -> None:
    # `rag_app`'s grants are exactly documents/chunks, so this binding would
    # make every history read `permission denied` — swallowed best-effort into
    # empty history, i.e. dead in production with a green suite.
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        rag = getattr(app.state, session_module._RAG_ENGINE_KEY)
        ops = getattr(app.state, session_module._OPS_ENGINE_KEY)
        assert ops is not rag
        assert ops.url != rag.url
    finally:
        await close_db(app)


async def test_ops_sessionmaker_is_bound_to_the_ops_engine(monkeypatch) -> None:
    # "never on the primary sessionmaker's engine" — the sessionmaker is the
    # object the request path actually reaches, so the binding is asserted
    # there and not only on the engine stored beside it.
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        ops_engine = getattr(app.state, session_module._OPS_ENGINE_KEY)
        primary_sm = getattr(app.state, session_module._SESSIONMAKER_KEY)
        ops_sm = getattr(app.state, session_module._OPS_SESSIONMAKER_KEY)
        assert ops_sm.kw["bind"] is ops_engine
        assert ops_sm.kw["bind"] is not primary_sm.kw["bind"]
    finally:
        await close_db(app)


async def test_three_engines_are_three_distinct_pools(monkeypatch) -> None:
    # §Diseño 7's pool argument: sharing the primary pool would double
    # per-request concurrency on the pool the atomic write needs.
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        pools = {
            id(getattr(app.state, key).pool)
            for key in (
                session_module._ENGINE_KEY,
                session_module._RAG_ENGINE_KEY,
                session_module._OPS_ENGINE_KEY,
            )
        }
        assert len(pools) == 3
    finally:
        await close_db(app)


async def test_ops_engine_absent_when_unconfigured(monkeypatch) -> None:
    # Inert by default: an unset DATABASE_URL_OPS creates no third engine and,
    # critically, does not fall back to either existing credential.
    monkeypatch.setattr(session_module, "settings", _settings(ops=None))
    app = _app()
    init_db(app)
    try:
        assert getattr(app.state, session_module._OPS_ENGINE_KEY) is None
        assert getattr(app.state, session_module._OPS_SESSIONMAKER_KEY) is None
    finally:
        await close_db(app)


# --- AC9: disposal ---------------------------------------------------------


async def test_close_db_disposes_the_ops_engine(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)

    engine = getattr(app.state, session_module._OPS_ENGINE_KEY)
    # `AsyncEngine.dispose` is a read-only attribute, so this asserts the
    # EFFECT rather than the call: `dispose()` closes the pool and replaces it
    # with a fresh one, so a changed pool identity is proof the engine was
    # actually disposed — and it stays true if the call is ever moved or
    # renamed.
    before = id(engine.pool)
    await close_db(app)
    assert id(engine.pool) != before


async def test_close_db_disposes_all_three_engines(monkeypatch) -> None:
    # The regression this pins is a new engine added to init_db without a
    # matching dispose in close_db — a leak that no other test would notice.
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)

    keys = {
        "primary": session_module._ENGINE_KEY,
        "rag": session_module._RAG_ENGINE_KEY,
        "ops": session_module._OPS_ENGINE_KEY,
    }
    engines = {label: getattr(app.state, key) for label, key in keys.items()}
    before = {label: id(engine.pool) for label, engine in engines.items()}

    await close_db(app)

    still_open = [label for label, engine in engines.items() if id(engine.pool) == before[label]]
    assert still_open == [], f"engines left undisposed: {still_open}"


async def test_close_db_tolerates_an_unconfigured_ops_engine(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "settings", _settings(ops=None))
    app = _app()
    init_db(app)
    await close_db(app)  # must not raise


# --- the seam --------------------------------------------------------------


async def test_seam_raises_a_distinct_type_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "settings", _settings(ops=None))
    app = _app()
    init_db(app)
    try:
        request = SimpleNamespace(app=app)
        with pytest.raises(OperationalDatabaseNotConfigured):
            get_history_sessionmaker(request)  # type: ignore[arg-type]
    finally:
        await close_db(app)


async def test_seam_returns_the_ops_sessionmaker(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "settings", _settings(ops=OPS_URL))
    app = _app()
    init_db(app)
    try:
        request = SimpleNamespace(app=app)
        assert get_history_sessionmaker(request) is getattr(  # type: ignore[arg-type]
            app.state, session_module._OPS_SESSIONMAKER_KEY
        )
    finally:
        await close_db(app)


async def test_seam_is_overridable_as_a_fastapi_dependency() -> None:
    """The seam's entire justification: `conftest` must be able to substitute it.

    Asserted through the real `dependency_overrides` mechanism rather than by
    reading the function, because "it is a callable" proves nothing about
    whether FastAPI actually resolves it as a dependency.
    """
    substitute = object()
    api = FastAPI()

    @api.get("/probe")
    async def probe(sm=Depends(get_history_sessionmaker)) -> dict:
        return {"substituted": sm is substitute}

    api.dependency_overrides[get_history_sessionmaker] = lambda: substitute
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"substituted": True}


async def test_short_lived_session_rolls_back_an_open_transaction() -> None:
    # Read-only does not mean transaction-free: SQLAlchemy opens one on first
    # execute, and an idle-in-transaction connection returned to the pool holds
    # a snapshot open.
    engine = create_async_engine(PRIMARY_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with short_lived_history_session(maker) as session:
            await session.connection()
            assert session.in_transaction()
            captured = session
        assert not captured.in_transaction()
    finally:
        await engine.dispose()


async def test_short_lived_session_closes_even_when_the_body_raises() -> None:
    engine = create_async_engine(PRIMARY_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    captured: list[AsyncSession] = []
    try:
        with pytest.raises(RuntimeError, match="boom"):
            async with short_lived_history_session(maker) as session:
                captured.append(session)
                await session.connection()
                raise RuntimeError("boom")
        assert not captured[0].in_transaction()
    finally:
        await engine.dispose()


# --- AC28: a seeded conversation yields NON-empty history, hermetically ----


@pytest.fixture
async def seeded_operational_db():
    """A real engine, a real schema from the real models, and real rows."""
    engine = create_async_engine(OPS_URL)
    conversation_id = uuid.uuid4()
    # Only the two tables the operational role reads. A blanket `create_all`
    # drags in `chunks`, whose TSVECTOR column SQLite cannot render — and the
    # RAG corpus is not what this credential touches anyway.
    history_tables = [Conversation.__table__, Message.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=history_tables)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        async with session.begin():
            session.add(Conversation(id=conversation_id, tenant_id=TENANT))
            await session.flush()
            for index, (role, content) in enumerate(
                ((MessageRole.user, "first question"),
                 (MessageRole.assistant, "first answer"),
                 (MessageRole.user, "second question")),
                start=1,
            ):
                session.add(
                    Message(
                        id=uuid.uuid4(),
                        sequence=index,
                        conversation_id=conversation_id,
                        tenant_id=TENANT,
                        role=role,
                        content=content,
                    )
                )
    try:
        yield maker, conversation_id
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all, tables=history_tables)
        await engine.dispose()


async def test_seeded_conversation_yields_non_empty_history(seeded_operational_db) -> None:
    maker, conversation_id = seeded_operational_db

    async with short_lived_history_session(maker) as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        messages = await adapter.fetch_ordered(conversation_id, TENANT)

    # The assertion AC28 exists for. An empty result here is the harness
    # silently disabling the feature, and it must be a failure, not a pass.
    assert messages, "seeded conversation produced empty history"
    assert [m.content for m in messages] == [
        "first question",
        "first answer",
        "second question",
    ]
    assert [m.role for m in messages] == ["user", "assistant", "user"]


async def test_history_is_ordered_by_sequence_not_insertion(seeded_operational_db) -> None:
    maker, conversation_id = seeded_operational_db
    async with short_lived_history_session(maker) as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        messages = await adapter.fetch_ordered(conversation_id, TENANT)
    sequences = [m.sequence for m in messages]
    assert sequences == sorted(sequences)


async def test_seam_and_seeded_database_compose(seeded_operational_db) -> None:
    """AC28 end to end: the override the harness would install actually works."""
    maker, conversation_id = seeded_operational_db
    api = FastAPI()

    @api.get("/history")
    async def history(sm=Depends(get_history_sessionmaker)) -> dict:
        async with short_lived_history_session(sm) as session:
            adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
            messages = await adapter.fetch_ordered(conversation_id, TENANT)
        return {"count": len(messages)}

    api.dependency_overrides[get_history_sessionmaker] = lambda: maker
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/history")

    assert response.status_code == 200
    assert response.json() == {"count": 3}


async def test_history_read_is_tenant_scoped_on_a_real_database(seeded_operational_db) -> None:
    # The port's contract (ADR-011 §2) over a real engine on the hermetic path;
    # AC10 asserts the same shape against PostgreSQL.
    from app.core.domain.conversation_history import ConversationNotFoundError

    maker, conversation_id = seeded_operational_db
    async with short_lived_history_session(maker) as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        with pytest.raises(ConversationNotFoundError):
            await adapter.fetch_ordered(conversation_id, "another-tenant")

