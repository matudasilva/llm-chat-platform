from __future__ import annotations

import json

import httpx
import pytest


def _sse_blocks(text: str) -> dict[str, str]:
    """Maps event name -> raw data payload for each `event: X\\ndata: Y` block."""
    blocks: dict[str, str] = {}
    for chunk in text.split("\n\n"):
        lines = [line for line in chunk.splitlines() if line]
        event = None
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if event is not None:
            blocks[event] = "\n".join(data_lines)
    return blocks


@pytest.mark.asyncio
async def test_streaming_chat_still_propagates_tenant_with_cors_enabled(
    client: httpx.AsyncClient,
) -> None:
    """ORQ-19.6: CORSMiddleware sits outermost now — real (non-preflight)
    requests, including the SSE stream, must still pass through
    TenantMiddleware exactly as before ORQ-19.6."""
    origin = "http://localhost:5173"

    r1 = await client.post(
        "/chat",
        json={"message": "hello", "stream": True},
        headers={"X-Tenant-ID": "tenant-a", "Origin": origin},
    )
    assert r1.status_code == 200
    assert r1.headers.get("access-control-allow-origin") == origin

    blocks = _sse_blocks(r1.text)
    assert "done" in blocks
    done_payload = json.loads(blocks["done"])
    conversation_id = done_payload["conversation_id"]

    # Continuing the same conversation under a different tenant must still be
    # rejected as not_found — proving tenant enforcement in the streaming
    # path is unaffected by CORSMiddleware now being the outermost layer.
    r2 = await client.post(
        "/chat",
        json={"message": "again", "stream": True, "conversation_id": conversation_id},
        headers={"X-Tenant-ID": "tenant-b", "Origin": origin},
    )
    assert r2.status_code == 200
    assert r2.headers.get("access-control-allow-origin") == origin

    blocks2 = _sse_blocks(r2.text)
    assert "error" in blocks2
    assert json.loads(blocks2["error"]) == {"error_kind": "not_found"}

    # And continuing under the original tenant still works.
    r3 = await client.post(
        "/chat",
        json={"message": "still me", "stream": True, "conversation_id": conversation_id},
        headers={"X-Tenant-ID": "tenant-a", "Origin": origin},
    )
    assert r3.status_code == 200
    blocks3 = _sse_blocks(r3.text)
    assert "done" in blocks3
    assert json.loads(blocks3["done"])["conversation_id"] == conversation_id
