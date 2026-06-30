from __future__ import annotations

import base64
import json
import logging
import re
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_DEFAULT_TENANT = "default"

_tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default=_DEFAULT_TENANT)


def get_tenant_id() -> str:
    return _tenant_id_ctx.get()


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        tenant_id = _extract_tenant_id(request)
        token = _tenant_id_ctx.set(tenant_id)
        request.state.tenant_id = tenant_id
        try:
            return await call_next(request)
        finally:
            _tenant_id_ctx.reset(token)


def _extract_tenant_id(request: Request) -> str:
    value = request.headers.get("X-Tenant-ID")
    if value is not None:
        return _validate(value)

    value = _from_jwt(request)
    if value is not None:
        return _validate(value)

    return _DEFAULT_TENANT


def _validate(value: str) -> str:
    stripped = value.strip()
    if stripped and _TENANT_ID_PATTERN.match(stripped):
        return stripped
    return _DEFAULT_TENANT


def _from_jwt(request: Request) -> str | None:
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
