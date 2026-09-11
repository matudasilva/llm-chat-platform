"""ORQ-37 H8/AC28 -- the shipped dependency, over a seeded database.

AC28: "On the hermetic path, a seeded conversation yields **non-empty**
history through the shipped dependency -- the criterion that fails if the
harness silently disables the feature."

Independent validation found the evidence split in half. Today
`test_operational_session.py` proves the ADAPTER returns non-empty history
over a seeded database, and separately that `dependency_overrides` works on a
`/history` route the test itself invents. Neither crosses
`get_chat_memory_context`, and `Depends(get_history_sessionmaker)` appears
**only** in those test-only routes -- production calls it directly
(`deps.py:135`, `chat.py:158`). The conjunction AC28 actually asks for was
never asserted.

**The seam is substitutable, through `app.state.ops_db_sessionmaker`**, which
is what `get_history_sessionmaker` reads and what the lifespan populates.
That is the mechanism these tests exercise, end to end, through the shipped
dependency.

Both halves matter and both are here:

* a seeded conversation reaches the model as non-empty history;
* an unconfigured operational database -- the SHIPPED DEFAULT, since
  `DATABASE_URL_OPS` is empty out of the box -- degrades to empty history
  instead of raising. That second half is why the seam is not a FastAPI
  dependency: as one, the raise would happen during dependency resolution and
  turn the default configuration into a 500, breaking invariant 7 (streaming
  answers an SSE error frame, never a 404/500) and AC13.

No runtime code is exercised differently here; nothing in `app/` changes.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.api import deps
from app.core.domain.chat_memory import ChatMemoryContext
from app.http import pipeline_metrics
from app.infra.db.base import Base
from app.models.conversation import Conversation  # noqa: F401  (registers the table)
from app.models.message import Message, MessageRole

pytestmark = pytest.mark.asyncio

OPS_URL = "sqlite+aiosqlite:///file:ac28-ops?mode=memory&cache=shared&uri=true"
TENANT = "acme"


@compiles(JSONB, "sqlite")
def _jsonb_renders_as_json_on_sqlite(type_, compiler, **kw) -> str:
    """Same DDL shim `test_operational_session.py` documents: `JSONB` cannot be
    rendered by the SQLite compiler, and production never asks it to. The
    tables still come from the real `Base.metadata`, so model drift breaks
    this test rather than silently passing it."""
    return "JSON"


@pytest.fixture
async def seeded_ops_db():
    """A real engine, the real schema from the real models, and real rows."""
    engine = create_async_engine(OPS_URL)
    conversation_id = uuid.uuid4()
    tables = [Conversation.__table__, Message.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=tables)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        async with session.begin():
            session.add(Conversation(id=conversation_id, tenant_id=TENANT))
            await session.flush()
            for index, (role, content) in enumerate(
                (
                    (MessageRole.user, "first question"),
                    (MessageRole.assistant, "first answer"),
                    (MessageRole.user, "second question"),
                    (MessageRole.assistant, "second answer"),
                ),
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
            await connection.run_sync(Base.metadata.drop_all, tables=tables)
        await engine.dispose()


@pytest.fixture
def collector():
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(uuid.uuid4()), correlation_id=None
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


@pytest.fixture
def memory_on(monkeypatch):
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 20, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_chars", 20000, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_rows", 2000, raising=False)
    monkeypatch.setattr(
        deps.settings, "chat_prompt_max_added_context_chars", 12000, raising=False
    )
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)
    return None


def _request(sessionmaker) -> SimpleNamespace:
    """A request whose `app.state` carries what the lifespan would install.

    This is the real substitution point: `get_history_sessionmaker` reads
    `request.app.state.ops_db_sessionmaker`, and nothing in production reads
    it any other way.
    """
    state = SimpleNamespace()
    if sessionmaker is not None:
        state.ops_db_sessionmaker = sessionmaker
    return SimpleNamespace(app=SimpleNamespace(state=state))


# --- AC28: the criterion, through the shipped dependency ------------------


async def test_seeded_conversation_reaches_the_model_through_the_dependency(
    seeded_ops_db, memory_on, collector
) -> None:
    """The conjunction AC28 asks for and that no test made: a seeded database,
    substituted at the real seam, read by the SHIPPED dependency, yielding
    non-empty history."""
    maker, conversation_id = seeded_ops_db

    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=conversation_id, message="what now"),
        _request(maker),
    )

    # "An empty result here is the harness silently disabling the feature, and
    # it must be a failure, not a pass."
    assert result.messages, "seeded conversation produced empty history"
    assert [m.content for m in result.messages] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
    ]
    assert [m.role for m in result.messages] == ["user", "assistant", "user", "assistant"]
    assert collector.snapshot()["memory_outcome"] == "ok"


async def test_a_conversation_owned_by_another_tenant_yields_nothing(
    seeded_ops_db, memory_on, collector, monkeypatch
) -> None:
    """The same seeded database, read for a different tenant. Non-empty here
    would be cross-tenant leakage; empty-because-broken and
    empty-because-forbidden must stay distinguishable, which the outcome is
    for."""
    maker, conversation_id = seeded_ops_db
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "someone-else")

    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=conversation_id, message="what now"),
        _request(maker),
    )

    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "conversation_not_found"


# --- the other half: the shipped default must degrade, not raise ----------


async def test_an_unconfigured_operational_database_degrades(
    memory_on, collector
) -> None:
    """`DATABASE_URL_OPS` is empty out of the box, so `app.state` carries no
    sessionmaker and the seam raises `OperationalDatabaseNotConfigured`. That
    must degrade to empty history, never propagate.

    This is the half that rules out declaring the seam as a FastAPI
    dependency: resolution happens before the handler body, so the raise would
    become a 500 in the default configuration -- breaking invariant 7, which
    requires the streaming path to answer an SSE error frame rather than a
    500, and AC13's never-raises contract.
    """
    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message="what now"),
        _request(None),
    )

    assert result == ChatMemoryContext()
    assert collector.snapshot()["memory_outcome"] == "error"


async def test_the_degradation_and_the_seeded_read_differ_only_in_the_seam(
    seeded_ops_db, memory_on, collector
) -> None:
    """Same dependency, same payload, same tenant: only `app.state` differs.
    Non-empty with the seam populated, empty without -- which is exactly the
    substitution AC28 says the harness must not be able to fake."""
    maker, conversation_id = seeded_ops_db
    payload = SimpleNamespace(conversation_id=conversation_id, message="what now")

    with_seam = await deps.get_chat_memory_context(payload, _request(maker))
    without_seam = await deps.get_chat_memory_context(payload, _request(None))

    assert with_seam.messages != ()
    assert without_seam.messages == ()
