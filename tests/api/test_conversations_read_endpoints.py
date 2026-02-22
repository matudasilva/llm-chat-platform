from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_conversation_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/conversations/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_conversation_includes_messages(client: httpx.AsyncClient) -> None:
    r1 = await client.post("/chat", json={"message": "hello"})
    assert r1.status_code == 200
    conversation_id = r1.json()["conversation_id"]

    r2 = await client.post("/chat", json={"conversation_id": conversation_id, "message": "second"})
    assert r2.status_code == 200

    r = await client.get(f"/conversations/{conversation_id}")
    assert r.status_code == 200

    body = r.json()
    assert body["id"] == conversation_id
    assert "created_at" in body
    assert "updated_at" in body
    assert isinstance(body["messages"], list)
    assert len(body["messages"]) >= 4

    roles = [m["role"] for m in body["messages"]]
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 2


@pytest.mark.asyncio
async def test_list_conversations_pagination_and_count(client: httpx.AsyncClient) -> None:
    r = await client.post("/chat", json={"message": "list test"})
    assert r.status_code == 200
    conversation_id = r.json()["conversation_id"]

    resp = await client.get("/conversations?limit=20&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    assert data["limit"] == 20
    assert data["offset"] == 0
    assert isinstance(data["items"], list)

    # OJO: probablemente tu list devuelve "id" (no "conversation_id").
    match = [it for it in data["items"] if it.get("id") == conversation_id or it.get("conversation_id") == conversation_id]
    assert match, "Expected created conversation in list"
    assert match[0]["message_count"] >= 2