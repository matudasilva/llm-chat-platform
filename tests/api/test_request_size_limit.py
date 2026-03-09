from __future__ import annotations

import httpx
import pytest

from app.core.settings import settings


@pytest.mark.asyncio
async def test_payload_over_max_request_bytes_returns_413(client: httpx.AsyncClient) -> None:
    oversized = b"a" * (settings.max_request_bytes + 1)

    r = await client.post(
        "/chat",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )

    assert r.status_code == 413
    assert r.json() == {"detail": "Payload too large"}