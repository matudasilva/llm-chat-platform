from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_BYPASS_PATHS = {"/health", "/healthz", "/readyz"}


class StagingGuardMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware, same reasoning as
    TenantMiddleware/ADR-003): this sits outermost, wrapping the /chat SSE
    response, and BaseHTTPMiddleware's separate-task response consumption
    is the exact pattern already avoided elsewhere in this app.

    Bypasses OPTIONS requests unconditionally: CORS preflights never carry
    the custom X-Staging-Key header, so gating them here would 401 every
    preflight and break CORS for the real frontend before the guard ever
    sees the actual request.
    """

    def __init__(self, app: ASGIApp, staging_key: str = "") -> None:
        self.app = app
        self._key = staging_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._key or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.url.path in _BYPASS_PATHS:
            await self.app(scope, receive, send)
            return

        if request.headers.get("X-Staging-Key") != self._key:
            response = JSONResponse({"detail": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
