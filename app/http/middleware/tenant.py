from __future__ import annotations

import base64
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_DEFAULT_TENANT = "default"

# `None` is the "never set" sentinel — distinct from the string "default",
# which TenantMiddleware/tenant_scope() set explicitly when no tenant was
# supplied. This lets get_tenant_id_strict() tell "nobody scoped this
# context" apart from "scoped to the default tenant on purpose" (ORQ-21 R1).
_tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)


class TenantContextError(RuntimeError):
    """Raised when tenant-scoped DB access runs without an explicitly set tenant context."""


def get_tenant_id() -> str:
    value = _tenant_id_ctx.get()
    return value if value is not None else _DEFAULT_TENANT


def get_tenant_id_strict() -> str:
    """
    Like get_tenant_id(), but raises instead of silently falling back to
    "default" when the ContextVar was never set.

    Used by TenantScopedSession.after_begin (app/infra/db/session.py) so
    that RAG DB access outside TenantMiddleware/tenant_scope() fails closed
    at transaction-begin instead of writing/reading under a "default"
    tenant nobody chose (ORQ-21 R1 — the fallback previously masked a
    missing tenant_scope() call as if it were a real, if generic, tenant).
    """
    value = _tenant_id_ctx.get()
    if value is None:
        raise TenantContextError(
            "tenant_id context not set — call tenant_scope(...) (offline/script code) "
            "or ensure TenantMiddleware is installed (HTTP requests) before opening a "
            "TenantScopedSession"
        )
    return value


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    """
    Explicit, non-HTTP counterpart to TenantMiddleware: sets the same
    ContextVar for callers with no request in flight.

    Required for the ORQ-21 offline ingestion pipeline (spec.md §Design
    decisions 8) — outside an HTTP request, get_tenant_id() silently returns
    the "default" tenant, which would write the whole corpus into the wrong
    tenant without erroring. The ingestion script must call this explicitly
    with its required --tenant-id argument rather than relying on the
    ContextVar default. Reuses the same TenantScopedSession.after_begin
    handler as the HTTP path (app/infra/db/session.py), so both paths set
    the `app.tenant_id` GUC identically.
    """
    validated = _validate(tenant_id)
    if validated != tenant_id:
        raise ValueError(f"invalid tenant_id: {tenant_id!r}")
    token = _tenant_id_ctx.set(validated)
    try:
        yield
    finally:
        _tenant_id_ctx.reset(token)


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
        if scope["type"] != "http":
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
