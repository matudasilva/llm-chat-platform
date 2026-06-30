from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.http.middleware.tenant import get_tenant_id
from app.http.request_context import get_correlation_id, get_request_id


class _DynamicStdoutHandler(logging.Handler):
    """Writes to sys.stdout dynamically so pytest capsys/capfd can capture it."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


class StructuredJsonLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, app_env: str):
        super().__init__(app)
        self.app_env = app_env
        self.logger = logging.getLogger("app.access")

        # Keep it isolated: one JSON line, no prefixes, no double logging
        self.logger.propagate = False

        if not any(isinstance(h, _DynamicStdoutHandler) for h in self.logger.handlers):
            handler = _DynamicStdoutHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code: Optional[int] = None

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))

            # Read from contextvars *after* request processing
            rid = request.headers.get("X-Request-ID") or get_request_id()
            cid = request.headers.get("X-Correlation-ID") or get_correlation_id()

            if rid is None or not str(rid).strip():
                rid = str(uuid.uuid4())
            if cid is None or not str(cid).strip():
                cid = str(rid)


            payload = {
                "request_id": str(rid),
                "correlation_id": str(cid),
                "tenant_id": get_tenant_id(),
                "path": request.url.path,
                "method": request.method,
                "status": int(status_code or 0),
                "latency_ms": latency_ms,
                "app_env": self.app_env,
            }
            self.logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
