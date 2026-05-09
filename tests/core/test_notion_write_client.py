from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.notion_write_client import NotionWriteClient, NotionWriteTransportError


@pytest.mark.asyncio
async def test_update_page_sends_expected_request() -> None:
    client = NotionWriteClient(
        api_token="token",
        base_url="https://api.notion.com/v1",
        api_version="2026-03-11",
        timeout_s=5.0,
    )

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={"id": "page-123"})

    fake_http_client = MagicMock()
    fake_http_client.request = AsyncMock(return_value=fake_response)
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.notion_write_client.httpx.AsyncClient", return_value=fake_http_client):
        result = await client.update_page(
            "page-123",
            {
                "Status": {"select": {"name": "done"}},
            },
        )

    assert result == {"id": "page-123"}
    fake_http_client.request.assert_awaited_once()
    method, path = fake_http_client.request.await_args.args[:2]
    assert method == "PATCH"
    assert path == "/pages/page-123"
    assert fake_http_client.request.await_args.kwargs["json"] == {
        "properties": {
            "Status": {"select": {"name": "done"}},
        }
    }


@pytest.mark.asyncio
async def test_create_row_sends_expected_request() -> None:
    client = NotionWriteClient(api_token="token")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={"id": "row-123"})

    fake_http_client = MagicMock()
    fake_http_client.request = AsyncMock(return_value=fake_response)
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.notion_write_client.httpx.AsyncClient", return_value=fake_http_client):
        result = await client.create_row(
            "db-123",
            {
                "Name": {"title": [{"text": {"content": "New Task"}}]},
            },
        )

    assert result == {"id": "row-123"}
    assert fake_http_client.request.await_args.args[:2] == ("POST", "/pages")
    assert fake_http_client.request.await_args.kwargs["json"] == {
        "parent": {"data_source_id": "db-123"},
        "properties": {
            "Name": {"title": [{"text": {"content": "New Task"}}]},
        },
    }


@pytest.mark.asyncio
async def test_update_page_includes_error_body_on_http_status_error() -> None:
    client = NotionWriteClient(api_token="token")

    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.text = '{"object":"error","status":400,"code":"validation_error","message":"Status is invalid"}'
    fake_response.json = MagicMock(return_value={"object": "error"})

    fake_http_client = MagicMock()
    fake_http_client.request = AsyncMock(return_value=fake_response)
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.notion_write_client.httpx.AsyncClient", return_value=fake_http_client):
        with pytest.raises(NotionWriteTransportError) as exc_info:
            await client.update_page("page-123", {"Status": {"status": {"name": "done"}}})

    assert "Notion API returned 400" in str(exc_info.value)
    assert "validation_error" in str(exc_info.value)
