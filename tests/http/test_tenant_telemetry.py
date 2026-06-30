from __future__ import annotations

import json
import logging

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
