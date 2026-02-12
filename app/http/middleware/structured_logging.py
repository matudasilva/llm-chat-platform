import json
import logging
import sys
import time
import uuid
from typing import Optional


class StructuredJsonLoggingMiddleware:
    """
    ASGI middleware: emits exactly one JSON log line per request (on response end).
    - No request/response bodies are logged.
    - request_id correlation order:
        1) scope["state"]["request_id"] (if your app sets it)
        2) incoming header X-Request-Id
        3) generated UUID4 (logging only)
    """

    def __init__(self, app, *, app_env: str):
        self.app = app
        self.app_env = app_env
        self.logger = logging.getLogger("app.access")
        self.logger.propagate = False
        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code: Optional[int] = None

        request_id = self._resolve_request_id(scope)
        method = scope.get("method", "")
        path = scope.get("path", "")

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
            payload = {
                "request_id": str(request_id),
                "path": path,
                "method": method,
                "status": int(status_code or 0),
                "latency_ms": latency_ms,
                "app_env": self.app_env,
            }
            # single-line JSON, cloud-friendly
            self.logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def _resolve_request_id(self, scope) -> uuid.UUID:
        state = scope.get("state") or {}
        candidate = state.get("request_id")
        if candidate:
            try:
                return uuid.UUID(str(candidate))
            except Exception:
                pass

        for k, v in scope.get("headers", []):
            if k.lower() == b"x-request-id":
                try:
                    return uuid.UUID(v.decode("utf-8"))
                except Exception:
                    break

        return uuid.uuid4()
