from __future__ import annotations

import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route as _Route
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.http.middleware.tenant import TenantMiddleware


async def _echo_tenant(request: Request) -> PlainTextResponse:
    return PlainTextResponse(request.state.tenant_id)


_app = Starlette(
    routes=[Route("/", _echo_tenant)],
    middleware=[Middleware(TenantMiddleware)],
)


def _make_bearer(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"Bearer {header}.{payload}."


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_header_sets_tenant_id(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-Tenant-ID": "acme"})
    assert r.text == "acme"


@pytest.mark.asyncio
async def test_fallback_when_no_header_and_no_jwt(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.text == "default"


@pytest.mark.asyncio
async def test_jwt_claim_used_when_no_header(client: AsyncClient) -> None:
    token = _make_bearer({"tenant_id": "beta-corp", "sub": "user1"})
    r = await client.get("/", headers={"Authorization": token})
    assert r.text == "beta-corp"


@pytest.mark.asyncio
async def test_jwt_without_tenant_claim_falls_back(client: AsyncClient) -> None:
    token = _make_bearer({"sub": "user1"})
    r = await client.get("/", headers={"Authorization": token})
    assert r.text == "default"


@pytest.mark.asyncio
async def test_header_takes_priority_over_jwt(client: AsyncClient) -> None:
    token = _make_bearer({"tenant_id": "from-jwt"})
    r = await client.get("/", headers={"X-Tenant-ID": "from-header", "Authorization": token})
    assert r.text == "from-header"


@pytest.mark.asyncio
async def test_invalid_tenant_id_in_header_falls_back(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-Tenant-ID": "bad value!"})
    assert r.text == "default"


@pytest.mark.asyncio
async def test_empty_tenant_id_in_header_falls_back(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-Tenant-ID": "   "})
    assert r.text == "default"


@pytest.mark.asyncio
async def test_tenant_id_too_long_falls_back(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-Tenant-ID": "a" * 65})
    assert r.text == "default"


@pytest.mark.asyncio
async def test_malformed_jwt_falls_back(client: AsyncClient) -> None:
    r = await client.get("/", headers={"Authorization": "Bearer not.a.valid.jwt.here"})
    assert r.text == "default"


# ---------------------------------------------------------------------------
# Task 4 corrections
# ---------------------------------------------------------------------------

def test_validate_rejects_non_string_values() -> None:
    from app.http.middleware.tenant import _validate

    assert _validate(42) == "default"
    assert _validate(None) == "default"
    assert _validate(["acme"]) == "default"
    assert _validate({"tenant_id": "acme"}) == "default"
    assert _validate(True) == "default"


@pytest.mark.asyncio
async def test_jwt_non_string_tenant_id_claim_falls_back(client: AsyncClient) -> None:
    token = _make_bearer({"tenant_id": 99})
    r = await client.get("/", headers={"Authorization": token})
    assert r.text == "default"


@pytest.mark.asyncio
async def test_context_var_preserved_during_streaming() -> None:
    from app.http.middleware.tenant import TenantMiddleware, get_tenant_id

    observed: list[str] = []

    async def streaming_handler(request: Request) -> StreamingResponse:
        async def body():
            for _ in range(3):
                observed.append(get_tenant_id())
                yield b"chunk"

        return StreamingResponse(body(), media_type="text/plain")

    stream_app = Starlette(
        routes=[_Route("/", streaming_handler)],
        middleware=[Middleware(TenantMiddleware)],
    )
    async with AsyncClient(transport=ASGITransport(app=stream_app), base_url="http://test") as c:
        r = await c.get("/", headers={"X-Tenant-ID": "stream-tenant"})

    assert r.status_code == 200
    assert len(observed) == 3
    assert all(v == "stream-tenant" for v in observed)
