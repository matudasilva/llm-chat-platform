from __future__ import annotations

import json
import uuid
import httpx
import pytest


@pytest.mark.asyncio
async def test_structured_logging_emits_json_line(client: httpx.AsyncClient, capsys) -> None:
    r = await client.get("/health")
    assert r.status_code == 200

    captured = capsys.readouterr()
    text = (captured.out or "") + "\n" + (captured.err or "")

    json_lines = [
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith('{"request_id"')
    ]
    assert len(json_lines) >= 1

    payload = json.loads(json_lines[-1])

    for key in ["request_id", "path", "method", "status", "latency_ms", "app_env"]:
        assert key in payload

    assert payload["path"] == "/health"
    assert payload["method"] == "GET"
    assert payload["status"] == 200
    assert int(payload["latency_ms"]) >= 0
    uuid.UUID(payload["request_id"])
    assert str(payload["app_env"]).strip() != ""