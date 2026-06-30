from __future__ import annotations

import base64
import json
import logging
import re
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_DEFAULT_TENANT = "default"

_tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default=_DEFAULT_TENANT)


def get_tenant_id() -> str:
    return _tenant_id_ctx.get()


class TenantContextFilter(logging.Filter):
    """Injects tenant_id from ContextVar into every log record (best-effort)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "tenant_id"):
            record.tenant_id = get_tenant_id()  # type: ignore[attr-defined]
        return True


class TenantMiddleware:
    """Pure ASGI middleware — ContextVar stays valid through entire streaming response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        tenant_id = _extract_tenant_id(request)
        request.state.tenant_id = tenant_id
        token = _tenant_id_ctx.set(tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _tenant_id_ctx.reset(token)


def _extract_tenant_id(request: Request) -> str:
    value = request.headers.get("X-Tenant-ID")
    if value is not None:
        return _validate(value)

    raw = _from_jwt(request)
    if raw is not None:
        return _validate(raw)

    return _DEFAULT_TENANT


def _validate(value: object) -> str:
    if not isinstance(value, str):
        return _DEFAULT_TENANT
    stripped = value.strip()
    if stripped and _TENANT_ID_PATTERN.match(stripped):
        return stripped
    return _DEFAULT_TENANT


def _from_jwt(request: Request) -> object | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:]
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return payload.get("tenant_id")
    except Exception:
        return None
