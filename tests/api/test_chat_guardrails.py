from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_chat_rejects_blank_message(client: httpx.AsyncClient) -> None:
    r = await client.post("/chat", json={"message": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_rejects_message_too_long(client: httpx.AsyncClient) -> None:
    r = await client.post("/chat", json={"message": "x" * 100_000})
    assert r.status_code in (413, 422)