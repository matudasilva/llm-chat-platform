from __future__ import annotations

import uuid
from typing import Callable, Iterable, List, Tuple

from app.core.observability import schema
from app.core.observability.tracing import span
from app.http.pipeline_metrics import init_collector, reset_collector
from app.http.request_context import (
    reset_request_context,
    reset_telemetry_identity,
    set_request_context,
    set_telemetry_identity,
    validate_correlation_id,
)

ASGIApp = Callable


class RequestContextMiddleware:
    """
    - Uses incoming X-Request-ID if present; otherwise generates a UUID.
    - Uses incoming X-Correlation-ID if present; otherwise defaults to request_id.
    - Stores both in contextvars.
    - Ensures both headers are present in every HTTP response.

    ORQ-37 T8 additionally mints the **telemetry** identity here, and this is
    the right place rather than "alongside TenantMiddleware": `add_middleware`
    is LIFO, so this middleware is added first (`main.py`) and is therefore the
    **innermost** of the stack. At any outer position `get_request_id()` still
    returns `None`, so nothing there could resolve or validate a header -- and
    the request span opened here is the innermost, which is what makes every
    downstream stage span its child.

    `RequestSizeLimitMiddleware` sits *outside* this one, so a request it
    rejects never reaches the collector and produces no metrics row. That is a
    declared consequence, not an oversight (AC26).
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

        # Telemetry identity is server-generated and never the inbound header.
        # `request_id_s` above may be arbitrary client text; this is not.
        request_instance_id = str(uuid.uuid4())
        telemetry_correlation_id = validate_correlation_id(
            request_id.decode("utf-8", errors="replace") if request_id else None
        )
        t3, t4 = set_telemetry_identity(request_instance_id, telemetry_correlation_id)

        # Present on every request that reaches here, regardless of
        # `conversation_history_enabled` or `chat_rag_augmentation_enabled`:
        # a collector that only existed when a feature was on could not record
        # the outcome of a request where that feature was off.
        _collector, collector_token = init_collector(
            request_instance_id=request_instance_id,
            correlation_id=telemetry_correlation_id,
        )

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                raw = message.get("headers") or []
                raw = _upsert_header(raw, b"x-request-id", request_id_s.encode("utf-8"))
                raw = _upsert_header(raw, b"x-correlation-id", correlation_id_s.encode("utf-8"))
                message["headers"] = raw
            await send(message)

        # The request span wraps the whole downstream call, streamed body
        # included, exactly as the context tokens do -- so stage spans become
        # its children and a streaming response stays inside it. The seam
        # swallows its own failures, so a broken tracer cannot affect any of
        # the resets below.
        attributes: dict[str, str] = {"request.instance_id": request_instance_id}
        if telemetry_correlation_id is not None:
            attributes["request.correlation_id"] = telemetry_correlation_id

        try:
            with span(schema.REQUEST_SPAN, **attributes):
                await self.app(scope, receive, send_wrapper)
        finally:
            reset_collector(collector_token)
            reset_telemetry_identity(t3, t4)
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
