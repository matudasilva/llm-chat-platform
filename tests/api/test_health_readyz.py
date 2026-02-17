from __future__ import annotations

import pytest


def test_healthz_always_200(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_ok_with_mocked_checker(client):
    class OkChecker:
        async def check(self):
            return {"status": "ok", "checks": {"db": "ok", "redis": "skipped"}}

    from app.services.readiness import get_readiness_checker
    client.app.dependency_overrides[get_readiness_checker] = lambda: OkChecker()

    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    client.app.dependency_overrides.clear()


def test_readyz_503_with_mocked_checker(client):
    class FailChecker:
        async def check(self):
            return {"status": "error", "checks": {"db": "error"}, "detail": "db unavailable"}

    from app.services.readiness import get_readiness_checker
    client.app.dependency_overrides[get_readiness_checker] = lambda: FailChecker()

    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "error"
    assert body["checks"]["db"] == "error"

    client.app.dependency_overrides.clear()

