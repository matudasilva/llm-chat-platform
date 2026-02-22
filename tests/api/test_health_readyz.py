from __future__ import annotations

import httpx
import pytest
from app.main import app


@pytest.mark.asyncio
async def test_healthz_always_200(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_readyz_ok_with_mocked_checker(client: httpx.AsyncClient) -> None:
    class OkChecker:
        async def check(self):
            return {"status": "ok", "checks": {"db": "ok", "redis": "skipped"}}

    from app.services.readiness import get_readiness_checker

    app.dependency_overrides[get_readiness_checker] = lambda: OkChecker()
    try:
        r = await client.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readyz_503_with_mocked_checker(client: httpx.AsyncClient) -> None:
    class FailChecker:
        async def check(self):
            return {"status": "error", "checks": {"db": "error"}, "detail": "db unavailable"}

    from app.services.readiness import get_readiness_checker

    app.dependency_overrides[get_readiness_checker] = lambda: FailChecker()
    try:
        r = await client.get("/readyz")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "error"
    finally:
        app.dependency_overrides.clear()