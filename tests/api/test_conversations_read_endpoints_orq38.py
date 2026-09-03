"""AC12 — the ORQ-38 tenant filter changes no route shape or response schema.

Scope is deliberately narrow. The `client` fixture overrides `get_db` with a
test session and these tests monkeypatch `ConversationQueryService`, so no SQL
is compiled or executed here: the double authors the rows it returns. What this
file establishes is only that adding `Message.tenant_id` to the query's WHERE
left the endpoint's contract untouched. Row-level filtering behaviour is proven
against a real database by the `postgres`-marked tests in
`tests/services/test_conversation_history_isolation_postgres.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.services.conversation_query_service import ConversationQueryService

CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
CREATED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _conversation() -> SimpleNamespace:
    return SimpleNamespace(
        id=CONVERSATION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def _messages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"),
            role="user",
            content="hello",
            created_at=CREATED_AT,
        ),
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"),
            role="assistant",
            content="hi",
            created_at=CREATED_AT,
        ),
    ]


@pytest.fixture
def doubled(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def fake_get_conversation(self, conversation_id: UUID, tenant_id: str):
        return _conversation()

    async def fake_list_messages(self, conversation_id: UUID, tenant_id: str):
        seen["tenant_id"] = tenant_id
        return _messages()

    monkeypatch.setattr(ConversationQueryService, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(
        ConversationQueryService, "list_messages_for_conversation", fake_list_messages
    )
    return seen


@pytest.mark.asyncio
async def test_response_schema_is_unchanged(
    client: httpx.AsyncClient, doubled: dict[str, object]
) -> None:
    resp = await client.get(f"/conversations/{CONVERSATION_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "created_at", "updated_at", "messages"}
    assert body["id"] == str(CONVERSATION_ID)
    assert len(body["messages"]) == 2
    for message in body["messages"]:
        assert set(message) == {"id", "role", "content", "created_at"}
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_route_still_forwards_the_tenant_id_it_always_did(
    client: httpx.AsyncClient, doubled: dict[str, object]
) -> None:
    # The signature did not change: tenant_id was already accepted and is still
    # passed. What changed is that the query now uses it.
    await client.get(f"/conversations/{CONVERSATION_ID}")

    assert doubled["tenant_id"] == "default"
