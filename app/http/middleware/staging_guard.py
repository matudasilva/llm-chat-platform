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

    def __init__(self, app: ASGIApp, staging_key: str = "", allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self._key = staging_key
        self._allowed_origins = set(allowed_origins or [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._key or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.url.path in _BYPASS_PATHS:
            await self.app(scope, receive, send)
            return

        if request.headers.get("X-Staging-Key") != self._key:
            # This response bypasses CORSMiddleware entirely (the guard sits
            # outside it), so without these headers the browser can't read a
            # cross-origin 401 at all — fetch() throws instead of returning a
            # response, and the frontend sees a generic network error instead
            # of "incorrect key". Mirror CORSMiddleware's allow-list here.
            headers = {}
            origin = request.headers.get("origin")
            if origin and origin in self._allowed_origins:
                headers["Access-Control-Allow-Origin"] = origin
                headers["Vary"] = "Origin"
            response = JSONResponse({"detail": "unauthorized"}, status_code=401, headers=headers)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
