"""
Tests for GET /notion-read/page endpoint with error mapping and validation.

Strategy: Test endpoint integration with the Notion read router only, using a
small FastAPI app to avoid unrelated startup behavior from the full application.
"""

import pytest
from fastapi import FastAPI
import httpx
from unittest.mock import AsyncMock

from app.api.routes.notion_read import router as notion_read_router
from app.services.notion_read import (
    NotionReadBlockedError,
    NotionReadError,
    NotionReadService,
)
from app.services.notion_read_client import (
    NotionMCPExecutionError,
    NotionMCPProtocolError,
    NotionMCPTimeoutError,
)


app = FastAPI()
app.include_router(notion_read_router)


def make_client():
    """Create an async HTTP client against the router-only test app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_get_page_success():
    """Test successful page fetch returns 200 with NotionPageOut."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.return_value = {
        "title": "Test Page",
        "url": "https://notion.so/test",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-01-02T00:00:00Z",
    }
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 200
    data = response.json()
    assert data["page_id"] == "abc123"
    assert data["title"] == "Test Page"
    assert data["url"] == "https://notion.so/test"
    assert data["created_time"] == "2026-01-01T00:00:00Z"
    assert data["last_edited_time"] == "2026-01-02T00:00:00Z"
    assert set(data.keys()) == {
        "page_id",
        "title",
        "url",
        "created_time",
        "last_edited_time",
    }
    mock_service.get_page.assert_awaited_once_with("abc123")


@pytest.mark.asyncio
async def test_get_page_missing_query_param():
    """Test missing page_id returns 422 (FastAPI validation)."""
    async with make_client() as client:
        response = await client.get("/notion-read/page")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_page_empty_query_param():
    """Test empty page_id returns 422 (FastAPI validation)."""
    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_page_blocked_returns_403():
    """Test blocked page returns 403 Forbidden."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionReadBlockedError(
        "Page not in allowlist"
    )
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=blocked-page")

    assert response.status_code == 403
    assert "denied" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_page_timeout_returns_504():
    """Test MCP timeout returns 504 Gateway Timeout."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPTimeoutError("Timeout")
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 504
    assert "timeout" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_page_protocol_error_returns_502():
    """Test MCP protocol error returns 502 Bad Gateway."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPProtocolError(
        "Subprocess failed"
    )
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 502
    assert "protocol" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_page_execution_error_returns_502():
    """Test MCP execution error returns 502 Bad Gateway."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPExecutionError(
        "Notion API error"
    )
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 502
    assert "error" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_page_service_error_returns_500():
    """Test service error returns 500 Internal Server Error."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionReadError("Unexpected error")
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_get_page_unexpected_error_returns_500():
    """Test unexpected exception returns 500."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = RuntimeError("Unexpected")
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_get_page_no_service_returns_503():
    """Test missing service returns 503 Service Unavailable."""
    if hasattr(app.state, "notion_read_service"):
        delattr(app.state, "notion_read_service")

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_page_response_schema_validation():
    """Test response is validated against NotionPageOut schema."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.return_value = {
        "url": "https://notion.so/test",
    }
    app.state.notion_read_service = mock_service

    async with make_client() as client:
        response = await client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "page_id": "abc123",
        "url": "https://notion.so/test",
        "title": None,
        "created_time": None,
        "last_edited_time": None,
    }
