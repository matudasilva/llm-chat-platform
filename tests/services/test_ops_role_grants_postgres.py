"""ORQ-37 T7 — the operational role's grants, at the database (AC34 B1 half, AC10).

`@pytest.mark.postgres`: skipped unless `RAG_TEST_DATABASE_URL` is set. A skip
is reported as a skip and never counted as a pass — AC10 says so explicitly,
and the same rule is what keeps this file honest: none of these properties can
be established against SQLite, because SQLite has no roles and no grants.

Gate B1 half only. The `rag_request_metrics` grants and the separate retention
credential are asserted at Gate B2, alongside the table T14 creates.

Two credentials are needed:

  * `RAG_TEST_DATABASE_URL` — a privileged DSN, used to seed and to inspect
    the catalog.
  * `CHAT_OPS_TEST_DATABASE_URL` — a DSN for the `chat_ops` role itself. The
    grant assertions are made by CONNECTING AS the role, not by reading
    `information_schema.role_table_grants`: a catalog row says a grant was
    written, while an actual denied `UPDATE` says the boundary holds. Only the
    second is the property AC34 claims.

Without the second DSN the connect-as-the-role tests skip individually and say
so, rather than degrading into catalog reads that would pass while the
boundary was open.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.domain.conversation_history import ConversationNotFoundError
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

OWNER = "orq37-ops-owner"
INTRUDER = "orq37-ops-intruder"
OPS_ROLE = "chat_ops"


def _admin_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _ops_url() -> str:
    url = os.environ.get("CHAT_OPS_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "CHAT_OPS_TEST_DATABASE_URL is not set; the grant boundary can only be "
            "asserted by connecting AS chat_ops, never from the catalog alone"
        )
    return url


@pytest.fixture
async def seeded():
    """Two conversations under different tenants, removed afterwards."""
    engine = create_async_engine(_admin_url())
    owned, foreign = uuid.uuid4(), uuid.uuid4()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            async with session.begin():
                for cid, tenant in ((owned, OWNER), (foreign, INTRUDER)):
                    await session.execute(
                        text("INSERT INTO conversations (id, tenant_id) VALUES (:id, :tenant)"),
                        {"id": cid, "tenant": tenant},
                    )
                for cid, tenant, role, body in (
                    (owned, OWNER, "user", "owned-user"),
                    (owned, OWNER, "assistant", "owned-assistant"),
                    (foreign, INTRUDER, "user", "foreign-user"),
                ):
                    await session.execute(
                        text(
                            "INSERT INTO messages (id, conversation_id, tenant_id, role, content) "
                            "VALUES (:id, :cid, :tenant, :role, :content)"
                        ),
                        {
                            "id": uuid.uuid4(),
                            "cid": cid,
                            "tenant": tenant,
                            "role": role,
                            "content": body,
                        },
                    )
        yield owned, foreign
    finally:
        async with maker() as session:
            async with session.begin():
                for cid in (owned, foreign):
                    await session.execute(
                        text("DELETE FROM messages WHERE conversation_id = :cid"), {"cid": cid}
                    )
                    await session.execute(
                        text("DELETE FROM conversations WHERE id = :cid"), {"cid": cid}
                    )
        await engine.dispose()


@pytest.fixture
async def ops_engine():
    engine = create_async_engine(_ops_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def admin_engine():
    engine = create_async_engine(_admin_url())
    try:
        yield engine
    finally:
        await engine.dispose()


# --- AC34 (B1 half): the role can read ------------------------------------


async def test_ops_role_can_select_conversations(ops_engine, seeded) -> None:
    owned, _ = seeded
    async with ops_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT tenant_id FROM conversations WHERE id = :id"), {"id": owned}
        )
        assert result.scalar_one() == OWNER


async def test_ops_role_can_select_messages(ops_engine, seeded) -> None:
    owned, _ = seeded
    async with ops_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT count(*) FROM messages WHERE conversation_id = :id"), {"id": owned}
        )
        assert result.scalar_one() == 2


async def test_ops_role_is_actually_chat_ops(ops_engine) -> None:
    # Guards the way this whole file could pass vacuously: a
    # CHAT_OPS_TEST_DATABASE_URL that is really the superuser DSN would satisfy
    # every SELECT and fail every denial assertion for the wrong reason.
    async with ops_engine.connect() as connection:
        assert (await connection.execute(text("SELECT current_user"))).scalar_one() == OPS_ROLE
        assert (await connection.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))).scalar_one() is False


# --- AC34 (B1 half): the role cannot write --------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE messages SET content = 'tampered' WHERE id = :id",
        "DELETE FROM messages WHERE id = :id",
    ],
    ids=["update", "delete"],
)
async def test_ops_role_cannot_write_messages(ops_engine, seeded, statement) -> None:
    # Invariant 1: the operational path must not become a second write-path.
    # Enforced at the database, so a future query bypassing the adapter still
    # cannot write.
    owned, _ = seeded
    async with ops_engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            await connection.execute(text(statement), {"id": owned})
    assert "permission denied" in str(excinfo.value).lower()


async def test_ops_role_cannot_insert_messages(ops_engine, seeded) -> None:
    owned, _ = seeded
    async with ops_engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            await connection.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, tenant_id, role, content) "
                    "VALUES (:id, :cid, :tenant, 'user', 'injected')"
                ),
                {"id": uuid.uuid4(), "cid": owned, "tenant": OWNER},
            )
    assert "permission denied" in str(excinfo.value).lower()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE conversations SET title = 'tampered' WHERE id = :id",
        "DELETE FROM conversations WHERE id = :id",
    ],
    ids=["update", "delete"],
)
async def test_ops_role_cannot_write_conversations(ops_engine, seeded, statement) -> None:
    owned, _ = seeded
    async with ops_engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            await connection.execute(text(statement), {"id": owned})
    assert "permission denied" in str(excinfo.value).lower()


# --- AC34 (B1 half): no RLS is introduced ---------------------------------


async def test_no_rls_on_conversations_or_messages(admin_engine) -> None:
    # §No-alcance: RLS on these tables stays ADR-004 §5's standing debt. This
    # asserts the ORQ did NOT quietly discharge it, which would change the
    # semantics of every existing read path.
    async with admin_engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('conversations', 'messages')"
            )
        )
        state = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    assert state, "conversations/messages not found in pg_class"
    for table, (enabled, forced) in state.items():
        assert enabled is False, f"RLS unexpectedly enabled on {table}"
        assert forced is False, f"RLS unexpectedly forced on {table}"


async def test_no_policies_on_conversations_or_messages(admin_engine) -> None:
    async with admin_engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE tablename IN ('conversations', 'messages')"
                )
            )
        ).scalar_one()
    assert count == 0


# --- AC10: the port's contract, over the operational credential -----------


async def test_adapter_returns_owned_history_over_the_ops_role(ops_engine, seeded) -> None:
    owned, _ = seeded
    maker = async_sessionmaker(ops_engine, expire_on_commit=False)
    async with maker() as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        messages = await adapter.fetch_ordered(owned, OWNER)
    # Non-empty over the real credential: the counterpart to AC28's hermetic
    # assertion, and what proves the grants above are sufficient rather than
    # merely non-fatal.
    assert [m.content for m in messages] == ["owned-user", "owned-assistant"]


async def test_adapter_raises_for_a_foreign_conversation(ops_engine, seeded) -> None:
    # ADR-011 §2: the port RAISES, it never returns an empty sequence — an
    # empty return would be indistinguishable from an empty conversation,
    # which is how isolation is lost silently. The dependency's opposite
    # contract (catch, never raise) is AC13's, at Gate B1's T9.
    _, foreign = seeded
    maker = async_sessionmaker(ops_engine, expire_on_commit=False)
    async with maker() as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        with pytest.raises(ConversationNotFoundError):
            await adapter.fetch_ordered(foreign, OWNER)


async def test_no_message_rows_leak_for_a_foreign_conversation(ops_engine, seeded) -> None:
    # AC10's second half, asserted separately: "returns no message rows". The
    # raise above says the guard fired; this says the message query underneath
    # it yields nothing even when driven directly.
    _, foreign = seeded
    maker = async_sessionmaker(ops_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await ConversationQueryService(session).list_messages_for_conversation(
            foreign, OWNER
        )
    assert rows == []
