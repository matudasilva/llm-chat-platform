from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.notion_write import (
    NotionWriteBlockedError,
    NotionWriteExecutionError,
    NotionWriteService,
    NotionWriteValidationError,
)


def _settings(**overrides):
    base = {
        "notion_write_enabled": True,
        "notion_api_token": "token",
        "notion_api_base_url": "https://api.notion.com/v1",
        "notion_api_version": "2026-03-11",
        "notion_write_timeout_s": 5.0,
        "notion_allowed_page_ids": ["pageabc123"],
        "notion_allowed_database_ids": ["dbxyz789"],
        "notion_editable_fields": {
            "pageabc123": {
                "status": {
                    "type": "status",
                    "options": ["todo", "done"],
                    "notion_property_name": "Status",
                },
                "title": {"type": "title"},
            },
            "row_in_dbxyz789": {
                "status": {
                    "type": "status",
                    "options": ["todo", "done"],
                    "notion_property_name": "Status",
                },
            },
        },
        "notion_database_templates": {
            "dbxyz789": {
                "Name": {"type": "title", "required": True},
                "Status": {
                    "type": "select",
                    "options": ["todo", "done"],
                    "required": True,
                    "notion_property_name": "Status",
                },
            }
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _Client:
    def __init__(self) -> None:
        self.update_page = AsyncMock(return_value={"id": "page-123"})
        self.create_row = AsyncMock(return_value={"id": "row-123"})
        self.update_row = AsyncMock(return_value={"id": "row-456"})


@pytest.mark.asyncio
async def test_write_page_success() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    result = await service.write_page("page-abc-123", {"status": "done"})

    assert result.status == "success"
    assert result.target_id == "page-abc-123"
    client.update_page.assert_awaited_once()
    assert client.update_page.await_args.kwargs["properties"] == {
        "Status": {"status": {"name": "done"}}
    }


@pytest.mark.asyncio
async def test_write_page_noop_skips_client() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    result = await service.write_page("page-abc-123", {})

    assert result.status == "noop"
    client.update_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_page_blocks_unknown_page() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    with pytest.raises(NotionWriteBlockedError, match="not in allowlist"):
        await service.write_page("page-invalid", {"status": "done"})


@pytest.mark.asyncio
async def test_write_page_rejects_invalid_value() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    with pytest.raises(NotionWriteValidationError, match="Invalid value"):
        await service.write_page("page-abc-123", {"status": "invalid"})


@pytest.mark.asyncio
async def test_create_row_success() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    result = await service.create_row(
        "db-xyz-789",
        {
            "Name": "New Task",
            "Status": "done",
        },
    )

    assert result.status == "success"
    client.create_row.assert_awaited_once()
    assert client.create_row.await_args.kwargs["properties"] == {
        "Name": {"title": [{"text": {"content": "New Task"}}]},
        "Status": {"select": {"name": "done"}},
    }


@pytest.mark.asyncio
async def test_create_row_blocks_unknown_database() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    with pytest.raises(NotionWriteBlockedError, match="not in allowlist"):
        await service.create_row("db-invalid", {"Name": "New Task", "Status": "done"})


@pytest.mark.asyncio
async def test_update_row_success() -> None:
    client = _Client()
    service = NotionWriteService(_settings(), client=client)

    result = await service.update_row("db-xyz-789", "row-456", {"status": "done"})

    assert result.status == "success"
    client.update_row.assert_awaited_once()
    assert client.update_row.await_args.kwargs["properties"] == {
        "Status": {"status": {"name": "done"}}
    }


@pytest.mark.asyncio
async def test_write_page_maps_client_failure_to_execution_error() -> None:
    client = _Client()
    client.update_page.side_effect = RuntimeError("boom")
    service = NotionWriteService(_settings(), client=client)

    with pytest.raises(NotionWriteExecutionError, match="boom"):
        await service.write_page("page-abc-123", {"status": "done"})
