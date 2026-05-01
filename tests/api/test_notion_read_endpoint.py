"""
Tests for GET /notion-read/page endpoint with error mapping and validation.

Strategy: Test endpoint integration with service, error code mapping, validation.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
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


@pytest.fixture
def client():
    """FastAPI test client with proper lifespan management."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def setup_service(monkeypatch):
    """Setup mock service in app state."""

    async def mock_service():
        return AsyncMock()

    return mock_service


def test_get_page_success(client, monkeypatch):
    """Test successful page fetch returns 200 with NotionPageOut."""
    # Setup mock service
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.return_value = {
        "page_id": "abc123",
        "title": "Test Page",
        "url": "https://notion.so/test",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-01-02T00:00:00Z",
    }

    # Inject service into app state
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 200
    data = response.json()
    assert data["page_id"] == "abc123"
    assert data["title"] == "Test Page"
    assert data["url"] == "https://notion.so/test"


def test_get_page_missing_query_param(client, monkeypatch):
    """Test missing page_id returns 422 (FastAPI validation)."""
    mock_service = AsyncMock(spec=NotionReadService)
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page")

    assert response.status_code == 422


def test_get_page_empty_query_param(client, monkeypatch):
    """Test empty page_id returns 422 (FastAPI validation)."""
    mock_service = AsyncMock(spec=NotionReadService)
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=")

    assert response.status_code == 422


def test_get_page_blocked_returns_403(client, monkeypatch):
    """Test blocked page returns 403 Forbidden."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionReadBlockedError(
        "Page not in allowlist"
    )
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=blocked-page")

    assert response.status_code == 403
    assert "denied" in response.json()["detail"].lower()


def test_get_page_timeout_returns_504(client, monkeypatch):
    """Test MCP timeout returns 504 Gateway Timeout."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPTimeoutError("Timeout")
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 504
    assert "timeout" in response.json()["detail"].lower()


def test_get_page_protocol_error_returns_502(client, monkeypatch):
    """Test MCP protocol error returns 502 Bad Gateway."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPProtocolError(
        "Subprocess failed"
    )
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 502
    assert "protocol" in response.json()["detail"].lower()


def test_get_page_execution_error_returns_502(client, monkeypatch):
    """Test MCP execution error returns 502 Bad Gateway."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionMCPExecutionError(
        "Notion API error"
    )
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 502
    assert "error" in response.json()["detail"].lower()


def test_get_page_service_error_returns_500(client, monkeypatch):
    """Test service error returns 500 Internal Server Error."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = NotionReadError("Unexpected error")
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 500


def test_get_page_unexpected_error_returns_500(client, monkeypatch):
    """Test unexpected exception returns 500."""
    mock_service = AsyncMock(spec=NotionReadService)
    mock_service.get_page.side_effect = RuntimeError("Unexpected")
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 500


def test_get_page_no_service_returns_503(client, monkeypatch):
    """Test missing service returns 503 Service Unavailable."""
    # Don't set the service in app state
    if hasattr(app.state, "notion_read_service"):
        delattr(app.state, "notion_read_service")

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_get_page_response_schema_validation(client, monkeypatch):
    """Test response is validated against NotionPageOut schema."""
    mock_service = AsyncMock(spec=NotionReadService)
    # Return minimal response (only required fields)
    mock_service.get_page.return_value = {
        "page_id": "abc123",
        "url": "https://notion.so/test",
    }
    app.state.notion_read_service = mock_service

    response = client.get("/notion-read/page?page_id=abc123")

    assert response.status_code == 200
    data = response.json()
    assert "page_id" in data
    assert "url" in data
