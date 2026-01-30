from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # Fast path: Content-Length header
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_bytes:
                    return JSONResponse(status_code=413, content={"detail": "Payload too large"})
            except ValueError:
                # Invalid header; fall back to body check.
                pass

        # Safe fallback: read body once (Starlette caches it) and validate
        body = await request.body()
        if len(body) > self._max_bytes:
            return JSONResponse(status_code=413, content={"detail": "Payload too large"})

        return await call_next(request)
