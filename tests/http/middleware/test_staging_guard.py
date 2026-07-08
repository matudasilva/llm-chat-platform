from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route

from app.http.middleware.staging_guard import StagingGuardMiddleware


async def _echo(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _make_client(staging_key: str) -> AsyncClient:
    app = Starlette(
        routes=[
            Route("/", _echo),
            Route("/health", _echo),
            Route("/healthz", _echo),
            Route("/readyz", _echo),
        ],
        middleware=[Middleware(StagingGuardMiddleware, staging_key=staging_key)],
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_guard_disabled_when_no_staging_key_passes_through() -> None:
    async with _make_client(staging_key="") as client:
        r = await client.get("/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_guard_enabled_with_correct_header_passes_through() -> None:
    async with _make_client(staging_key="secret123") as client:
        r = await client.get("/", headers={"X-Staging-Key": "secret123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_guard_enabled_with_wrong_header_is_unauthorized() -> None:
    async with _make_client(staging_key="secret123") as client:
        r = await client.get("/", headers={"X-Staging-Key": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_guard_enabled_with_missing_header_is_unauthorized() -> None:
    async with _make_client(staging_key="secret123") as client:
        r = await client.get("/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_guard_enabled_bypasses_health_paths_without_header() -> None:
    async with _make_client(staging_key="secret123") as client:
        for path in ("/health", "/healthz", "/readyz"):
            r = await client.get(path)
            assert r.status_code == 200, path


@pytest.mark.asyncio
async def test_guard_enabled_bypasses_options_preflight_without_header() -> None:
    # Real CORS preflights never carry X-Staging-Key. If this weren't bypassed,
    # StagingGuardMiddleware sitting outermost (outside CORSMiddleware) would
    # 401 every preflight and break CORS for the actual frontend origin.
    async with _make_client(staging_key="secret123") as client:
        r = await client.options("/")
    assert r.status_code != 401


@pytest.mark.asyncio
async def test_guard_does_not_disrupt_streaming_response() -> None:
    observed: list[bytes] = []

    async def streaming_handler(request: Request) -> StreamingResponse:
        async def body():
            for i in range(3):
                chunk = f"chunk-{i}".encode()
                observed.append(chunk)
                yield chunk

        return StreamingResponse(body(), media_type="text/plain")

    app = Starlette(
        routes=[Route("/stream", streaming_handler)],
        middleware=[Middleware(StagingGuardMiddleware, staging_key="secret123")],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/stream", headers={"X-Staging-Key": "secret123"})

    assert r.status_code == 200
    assert r.text == "chunk-0chunk-1chunk-2"
    assert len(observed) == 3
