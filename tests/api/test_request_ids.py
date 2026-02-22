from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_chat_response_request_id_matches_header(client: httpx.AsyncClient) -> None:
    r = await client.post("/chat", json={"message": "hello"})
    assert r.status_code == 200

    header_rid = r.headers.get("x-request-id")
    assert header_rid is not None

    body = r.json()
    assert body["request_id"] == header_rid