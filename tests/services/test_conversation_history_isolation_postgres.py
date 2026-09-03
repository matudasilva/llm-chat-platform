"""Real-database isolation for the ORQ-38 history substrate (AC17).

Skipped unless RAG_TEST_DATABASE_URL is set -- the same condition §Diseño 3
calls "unreachable", so a skip here and an unreachable T3 always co-occur.
Nothing here is proven by a double: the point is that the WHERE filters and the
ORDER BY actually behave against PostgreSQL.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.domain.conversation_history import ConversationNotFoundError
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

OWNER = "orq38-owner"
INTRUDER = "orq38-intruder"


def _url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


@pytest.fixture
async def seeded():
    """Two conversations under different tenants, removed afterwards."""
    engine = create_async_engine(_url())
    owned, foreign = uuid.uuid4(), uuid.uuid4()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            async with session.begin():
                for cid, tenant in ((owned, OWNER), (foreign, INTRUDER)):
                    await session.execute(
                        text(
                            "INSERT INTO conversations (id, tenant_id) "
                            "VALUES (:id, :tenant)"
                        ),
                        {"id": cid, "tenant": tenant},
                    )
                for cid, tenant, body in (
                    (owned, OWNER, "owned-user"),
                    (owned, OWNER, "owned-assistant"),
                    (foreign, INTRUDER, "foreign-user"),
                ):
                    role = "assistant" if body.endswith("assistant") else "user"
                    await session.execute(
                        text(
                            "INSERT INTO messages "
                            "(id, conversation_id, tenant_id, role, content) "
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
        yield engine, owned, foreign
    finally:
        async with maker() as session:
            async with session.begin():
                await session.execute(
                    text("DELETE FROM messages WHERE tenant_id = ANY(:t)"),
                    {"t": [OWNER, INTRUDER]},
                )
                await session.execute(
                    text("DELETE FROM conversations WHERE tenant_id = ANY(:t)"),
                    {"t": [OWNER, INTRUDER]},
                )
        await engine.dispose()


async def test_returns_only_the_requested_conversation(seeded) -> None:
    engine, owned, _ = seeded
    async with async_sessionmaker(engine)() as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        messages = await adapter.fetch_ordered(owned, OWNER)

    assert [m.content for m in messages] == ["owned-user", "owned-assistant"]
    assert [m.sequence for m in messages] == sorted(m.sequence for m in messages)


async def test_raises_for_a_conversation_owned_by_another_tenant(seeded) -> None:
    engine, _, foreign = seeded
    async with async_sessionmaker(engine)() as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        with pytest.raises(ConversationNotFoundError):
            await adapter.fetch_ordered(foreign, OWNER)


async def test_layer_2_excludes_a_tenant_divergent_row(seeded) -> None:
    """Layer 2 shipped (T3 = 0), so a divergent row must not be returned."""
    engine, owned, _ = seeded
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, tenant_id, role, content) "
                    "VALUES (:id, :cid, :tenant, 'user', 'divergent')"
                ),
                {"id": uuid.uuid4(), "cid": owned, "tenant": INTRUDER},
            )

    async with maker() as session:
        adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
        messages = await adapter.fetch_ordered(owned, OWNER)

    assert "divergent" not in [m.content for m in messages]
