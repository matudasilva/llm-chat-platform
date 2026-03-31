from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.services.conversation_query_service import ConversationListRow, ConversationQueryService


CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
CREATED_AT = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
UPDATED_AT = datetime(2026, 3, 31, 12, 5, tzinfo=timezone.utc)


def _conversation() -> SimpleNamespace:
    return SimpleNamespace(
        id=CONVERSATION_ID,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )


def _messages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"),
            role="user",
            content="hello",
            created_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"),
            role="assistant",
            content="hi",
            created_at=datetime(2026, 3, 31, 12, 0, 1, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3"),
            role="user",
            content="second",
            created_at=datetime(2026, 3, 31, 12, 0, 2, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4"),
            role="assistant",
            content="reply",
            created_at=datetime(2026, 3, 31, 12, 0, 3, tzinfo=timezone.utc),
        ),
    ]


@pytest.mark.asyncio
async def test_get_conversation_404(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_conversation(
        self,
        conversation_id: UUID,
    ) -> None:
        return None

    monkeypatch.setattr(
        ConversationQueryService,
        "get_conversation",
        fake_get_conversation,
    )

    resp = await client.get("/conversations/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_conversation_includes_messages(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_conversation(
        self,
        conversation_id: UUID,
    ) -> SimpleNamespace:
        assert conversation_id == CONVERSATION_ID
        return _conversation()

    async def fake_list_messages_for_conversation(
        self,
        conversation_id: UUID,
    ) -> list[SimpleNamespace]:
        assert conversation_id == CONVERSATION_ID
        return _messages()

    monkeypatch.setattr(
        ConversationQueryService,
        "get_conversation",
        fake_get_conversation,
    )
    monkeypatch.setattr(
        ConversationQueryService,
        "list_messages_for_conversation",
        fake_list_messages_for_conversation,
    )

    r = await client.get(f"/conversations/{CONVERSATION_ID}")
    assert r.status_code == 200

    body = r.json()
    assert body["id"] == str(CONVERSATION_ID)
    assert body["created_at"] == CREATED_AT.isoformat().replace("+00:00", "Z")
    assert body["updated_at"] == UPDATED_AT.isoformat().replace("+00:00", "Z")
    assert list(body.keys()) == ["id", "created_at", "updated_at", "messages"]
    assert isinstance(body["messages"], list)
    assert len(body["messages"]) == 4

    roles = [message["role"] for message in body["messages"]]
    contents = [message["content"] for message in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert contents == ["hello", "hi", "second", "reply"]


@pytest.mark.asyncio
async def test_list_conversations_pagination_and_count(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_list_conversations(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[ConversationListRow]:
        assert limit == 20
        assert offset == 0
        return [
            ConversationListRow(
                conversation_id=CONVERSATION_ID,
                created_at=CREATED_AT,
                updated_at=UPDATED_AT,
                message_count=4,
            )
        ]

    monkeypatch.setattr(
        ConversationQueryService,
        "list_conversations",
        fake_list_conversations,
    )

    resp = await client.get("/conversations?limit=20&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    assert data["limit"] == 20
    assert data["offset"] == 0
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1
    assert data["items"][0]["conversation_id"] == str(CONVERSATION_ID)
    assert data["items"][0]["message_count"] == 4
    assert data["items"][0]["created_at"] == CREATED_AT.isoformat().replace("+00:00", "Z")
    assert data["items"][0]["updated_at"] == UPDATED_AT.isoformat().replace("+00:00", "Z")
