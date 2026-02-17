from __future__ import annotations

import uuid
from typing import Callable, Iterable, List, Tuple

from app.http.request_context import reset_request_context, set_request_context

ASGIApp = Callable


class RequestContextMiddleware:
    """
    - Uses incoming X-Request-ID if present; otherwise generates a UUID.
    - Uses incoming X-Correlation-ID if present; otherwise defaults to request_id.
    - Stores both in contextvars.
    - Ensures both headers are present in every HTTP response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers_to_dict(scope.get("headers") or [])
        request_id = headers.get(b"x-request-id")
        correlation_id = headers.get(b"x-correlation-id")

        if request_id is None or not request_id.strip():
            request_id_s = str(uuid.uuid4())
        else:
            request_id_s = request_id.decode("utf-8", errors="replace").strip()

        if correlation_id is None or not correlation_id.strip():
            correlation_id_s = request_id_s
        else:
            correlation_id_s = correlation_id.decode("utf-8", errors="replace").strip()

        t1, t2 = set_request_context(request_id_s, correlation_id_s)

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                raw = message.get("headers") or []
                raw = _upsert_header(raw, b"x-request-id", request_id_s.encode("utf-8"))
                raw = _upsert_header(raw, b"x-correlation-id", correlation_id_s.encode("utf-8"))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_request_context(t1, t2)


def _headers_to_dict(headers: Iterable[Tuple[bytes, bytes]]) -> dict[bytes, bytes]:
    # ASGI headers are (key, value) bytes; keys are case-insensitive.
    d: dict[bytes, bytes] = {}
    for k, v in headers:
        d[k.lower()] = v
    return d


def _upsert_header(headers: List[Tuple[bytes, bytes]], key: bytes, value: bytes) -> List[Tuple[bytes, bytes]]:
    key_l = key.lower()
    # Remove any existing header with same key (case-insensitive) then append one.
    out = [(k, v) for (k, v) in headers if k.lower() != key_l]
    out.append((key_l, value))
    return out
