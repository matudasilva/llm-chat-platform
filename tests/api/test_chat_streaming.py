import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_streaming_sse_smoke(client: AsyncClient) -> None:
    payload = {"message": "hello", "stream": True}

    tokens_seen = 0
    done_payload = None

    async with client.stream("POST", "/chat", json=payload) as r:
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/event-stream")

        current_event = None
        async for line in r.aiter_lines():
            if not line:
                continue

            if line.startswith("event: "):
                current_event = line.removeprefix("event: ").strip()
                continue

            if line.startswith("data: "):
                data = line.removeprefix("data: ").strip()

                if current_event == "token":
                    tokens_seen += 1
                elif current_event == "done":
                    done_payload = json.loads(data)
                    break
                elif current_event == "error":
                    # If this happens, the test should fail; print info for debugging
                    err = json.loads(data)
                    pytest.fail(f"stream error: {err}")

    assert tokens_seen >= 1
    assert done_payload is not None
    assert "conversation_id" in done_payload
    assert "request_id" in done_payload
    assert done_payload.get("status") == "success"
    assert "user_message_id" in done_payload
    assert "assistant_message_id" in done_payload
    
    conversation_id = done_payload["conversation_id"]
    r2 = await client.get(f"/conversations/{conversation_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == conversation_id
    assert len(body.get("messages", [])) >= 2