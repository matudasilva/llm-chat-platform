from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Generator

import httpx
import pytest

from app.http.middleware.tenant import TenantContextFilter, _tenant_id_ctx


# ---------------------------------------------------------------------------
# Unit tests: TenantContextFilter
# ---------------------------------------------------------------------------

def test_filter_injects_tenant_id_from_context_var() -> None:
    filt = TenantContextFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test", args=(), exc_info=None,
    )
    token = _tenant_id_ctx.set("filter-tenant")
    try:
        result = filt.filter(record)
    finally:
        _tenant_id_ctx.reset(token)

    assert result is True
    assert record.tenant_id == "filter-tenant"  # type: ignore[attr-defined]


def test_filter_preserves_existing_tenant_id() -> None:
    filt = TenantContextFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test", args=(), exc_info=None,
    )
    record.tenant_id = "already-set"  # type: ignore[attr-defined]

    token = _tenant_id_ctx.set("different-tenant")
    try:
        filt.filter(record)
    finally:
        _tenant_id_ctx.reset(token)

    assert record.tenant_id == "already-set"  # not overwritten


def test_root_handler_formats_with_tenant_id() -> None:
    """Verify the root StreamHandler applies TenantContextFilter and formats tenant_id."""
    root = logging.getLogger()
    handler = next(
        (h for h in root.handlers if isinstance(h, logging.StreamHandler)), None
    )
    assert handler is not None, "root StreamHandler not found — main.py may not be imported"

    record = logging.LogRecord(
        name="app.probe", level=logging.INFO, pathname="", lineno=0,
        msg="probe", args=(), exc_info=None,
    )

    token = _tenant_id_ctx.set("fmt-tenant")
    try:
        handler.filter(record)   # TenantContextFilter injects tenant_id
        formatted = handler.format(record)
    finally:
        _tenant_id_ctx.reset(token)

    assert getattr(record, "tenant_id", None) == "fmt-tenant"
    assert "tenant_id=fmt-tenant" in formatted


# ---------------------------------------------------------------------------
# Integration test: access log JSON contains correct tenant_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_access_log_json_contains_tenant_id(
    client: httpx.AsyncClient, capsys
) -> None:
    r = await client.get("/health", headers={"X-Tenant-ID": "access-tenant"})
    assert r.status_code == 200

    captured = capsys.readouterr()
    text = (captured.out or "") + "\n" + (captured.err or "")

    json_lines = [
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith('{"request_id"')
    ]
    assert json_lines, "no access log JSON line found"
    payload = json.loads(json_lines[-1])
    assert payload.get("tenant_id") == "access-tenant"


@pytest.mark.asyncio
async def test_access_log_json_defaults_to_default_when_no_header(
    client: httpx.AsyncClient, capsys
) -> None:
    r = await client.get("/health")
    assert r.status_code == 200

    captured = capsys.readouterr()
    text = (captured.out or "") + "\n" + (captured.err or "")

    json_lines = [
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith('{"request_id"')
    ]
    assert json_lines
    payload = json.loads(json_lines[-1])
    assert payload.get("tenant_id") == "default"


# ---------------------------------------------------------------------------
# Representative telemetry tests — real loggers from provider/chat/cache
# ---------------------------------------------------------------------------

class _RecordCollector(logging.Handler):
    """Captures LogRecords and applies TenantContextFilter (same as root handler)."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(TenantContextFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture(logger_name: str, tenant: str) -> Generator[_RecordCollector, None, None]:
    collector = _RecordCollector()
    lg = logging.getLogger(logger_name)
    lg.addHandler(collector)
    token = _tenant_id_ctx.set(tenant)
    try:
        yield collector
    finally:
        _tenant_id_ctx.reset(token)
        lg.removeHandler(collector)


def test_provider_event_receives_tenant_id() -> None:
    """provider.* logger emits records that get tenant_id injected by TenantContextFilter."""
    with _capture("app.core.providers.openai_provider", "prov-tenant") as col:
        logging.getLogger("app.core.providers.openai_provider").info(
            "provider.request",
            extra={
                "event": "provider.request",
                "provider": "openai",
                "model": "gpt-4o",
                "request_id": "test-req",
                "messages_count": 1,
                "attempt": 1,
            },
        )

    assert len(col.records) == 1
    assert getattr(col.records[0], "tenant_id", None) == "prov-tenant"
    assert col.records[0].__dict__.get("event") == "provider.request"


def test_chat_event_receives_tenant_id() -> None:
    """chat.* logger emits records that get tenant_id injected by TenantContextFilter."""
    with _capture("app.api.routes.chat", "chat-tenant") as col:
        logging.getLogger("app.api.routes.chat").info(
            "chat_streaming_start request_id=%s conversation_id=%s is_new=%s",
            "req-1",
            "conv-1",
            "True",
        )

    assert len(col.records) == 1
    assert getattr(col.records[0], "tenant_id", None) == "chat-tenant"


def test_cache_bypass_event_receives_tenant_id() -> None:
    """cache.bypass is logged via ChatResponseCache.log_bypass(); TenantContextFilter injects tenant."""
    from app.services.chat_response_cache import ChatResponseCache

    cache = ChatResponseCache()
    with _capture("app.services.chat_response_cache", "bypass-tenant") as col:
        cache.log_bypass(reason="streaming")

    assert len(col.records) == 1
    record = col.records[0]
    assert getattr(record, "tenant_id", None) == "bypass-tenant"
    assert record.__dict__.get("event") == "chat.cache.bypass"
    assert record.__dict__.get("reason") == "streaming"


def test_non_http_scope_is_passed_through_without_setting_tenant() -> None:
    """TenantMiddleware delegates non-HTTP scopes without touching the ContextVar."""
    import asyncio
    from app.http.middleware.tenant import TenantMiddleware, get_tenant_id

    observed: list[str] = []

    async def inner_app(scope, receive, send):
        observed.append(get_tenant_id())

    async def run():
        middleware = TenantMiddleware(inner_app)
        await middleware({"type": "lifespan"}, None, None)
        await middleware({"type": "websocket", "headers": []}, None, None)

    asyncio.get_event_loop().run_until_complete(run())

    assert observed == ["default", "default"]
