from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import app.http.middleware.tenant as tenant_module
from app.http.middleware.tenant import TenantMiddleware

# Mirrors the production order in app/main.py: CORSMiddleware is the
# outermost layer (registered after TenantMiddleware via add_middleware(),
# which is LIFO), so OPTIONS preflights never reach TenantMiddleware while
# real requests still do.


async def _handler(request: Request) -> PlainTextResponse:
    return PlainTextResponse(f"handler-reached:{request.state.tenant_id}")


def _make_app(allow_origins: list[str]) -> Starlette:
    return Starlette(
        routes=[Route("/", _handler, methods=["GET", "POST"])],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                allow_credentials=False,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-Tenant-ID"],
            ),
            Middleware(TenantMiddleware),
        ],
    )


def _client_for(allow_origins: list[str]) -> AsyncClient:
    app = _make_app(allow_origins)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_preflight_with_default_origin_is_answered_by_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        tenant_module,
        "_extract_tenant_id",
        lambda request: calls.append("called") or "should-not-happen",
    )

    async with _client_for(["http://localhost:5173"]) as client:
        r = await client.options(
            "/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    # The preflight never reached TenantMiddleware — it short-circuited at CORS.
    assert calls == []


@pytest.mark.asyncio
async def test_preflight_with_x_tenant_id_in_request_headers_is_answered_by_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        tenant_module,
        "_extract_tenant_id",
        lambda request: calls.append("called") or "should-not-happen",
    )

    async with _client_for(["http://localhost:5173"]) as client:
        r = await client.options(
            "/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-tenant-id",
            },
        )

    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    allow_headers = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-tenant-id" in allow_headers
    assert calls == []


@pytest.mark.asyncio
async def test_multiple_configured_origins_are_both_allowed() -> None:
    async with _client_for(["http://localhost:5173", "http://localhost:4000"]) as client:
        r1 = await client.options(
            "/",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        r2 = await client.options(
            "/",
            headers={"Origin": "http://localhost:4000", "Access-Control-Request-Method": "GET"},
        )

    assert r1.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r2.headers.get("access-control-allow-origin") == "http://localhost:4000"


@pytest.mark.asyncio
async def test_origin_outside_the_configured_list_gets_no_permissive_cors_headers() -> None:
    async with _client_for(["http://localhost:5173"]) as client:
        r = await client.options(
            "/",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )

    assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


@pytest.mark.asyncio
async def test_real_get_request_still_reaches_tenant_middleware_with_cors_enabled() -> None:
    async with _client_for(["http://localhost:5173"]) as client:
        r = await client.get(
            "/",
            headers={"Origin": "http://localhost:5173", "X-Tenant-ID": "acme"},
        )

    assert r.status_code == 200
    assert r.text == "handler-reached:acme"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
