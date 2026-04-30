"""
Tests for NotionReadService allowlist, normalization, sanitization.

Strategy: Mock client, test allowlist enforcement, ID normalization, response sanitization.
"""

import pytest
from unittest.mock import AsyncMock

from app.core.settings import Settings
from app.services.notion_read import (
    NotionReadBlockedError,
    NotionReadError,
    NotionReadService,
)
from app.services.notion_read_client import NotionMCPExecutionError


@pytest.fixture
def settings_with_allowlist():
    """Settings with Notion Read enabled and allowlist configured."""
    return Settings(
        notion_read_enabled=True,
        notion_mcp_enabled=True,
        notion_allowed_page_ids=["abc-123", "def-456"],  # dashes will be normalized
    )


@pytest.fixture
def settings_no_allowlist():
    """Settings with no page IDs in allowlist."""
    return Settings(
        notion_read_enabled=True,
        notion_mcp_enabled=True,
        notion_allowed_page_ids=[],
    )


@pytest.fixture
def mock_client():
    """Mock ControlledNotionReadClient."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_get_page_success(mock_client, settings_with_allowlist):
    """Test successful page fetch with allowlist enforcement."""
    service = NotionReadService(mock_client, settings_with_allowlist)

    # Mock client response
    mock_client.get_page.return_value = {
        "page_id": "abc123",
        "title": "Test Page",
        "url": "https://notion.so/test",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-01-02T00:00:00Z",
        "text": "should be removed",  # Will be sanitized out
        "internal_field": "secret",  # Will be sanitized out
    }

    result = await service.get_page("abc-123")  # normalized to abc123

    # Should sanitize response
    assert result["page_id"] == "abc123"
    assert result["title"] == "Test Page"
    assert result["url"] == "https://notion.so/test"
    assert result["created_time"] == "2026-01-01T00:00:00Z"
    assert result["last_edited_time"] == "2026-01-02T00:00:00Z"
    assert "text" not in result
    assert "internal_field" not in result


@pytest.mark.asyncio
async def test_get_page_blocked_not_in_allowlist(mock_client, settings_with_allowlist):
    """Test access denied for page_id not in allowlist."""
    service = NotionReadService(mock_client, settings_with_allowlist)

    with pytest.raises(NotionReadBlockedError, match="not in allowlist"):
        await service.get_page("xyz-999")


@pytest.mark.asyncio
async def test_get_page_blocked_empty_allowlist(mock_client, settings_no_allowlist):
    """Test access denied when allowlist is empty."""
    service = NotionReadService(mock_client, settings_no_allowlist)

    with pytest.raises(NotionReadBlockedError):
        await service.get_page("abc-123")


@pytest.mark.asyncio
async def test_id_normalization_removes_dashes(mock_client, settings_with_allowlist):
    """Test ID normalization removes dashes for comparison."""
    service = NotionReadService(mock_client, settings_with_allowlist)

    mock_client.get_page.return_value = {
        "page_id": "abc123",
        "url": "https://notion.so/test",
    }

    # Test that "abc-123" matches normalized allowlist "abc123"
    result = await service.get_page("abc-123")

    assert result["page_id"] == "abc123"
    mock_client.get_page.assert_called_once_with("abc-123")


@pytest.mark.asyncio
async def test_sanitization_metadata_only(mock_client, settings_with_allowlist):
    """Test response sanitization extracts only metadata fields."""
    service = NotionReadService(mock_client, settings_with_allowlist)

    mock_client.get_page.return_value = {
        "page_id": "abc123",
        "title": "Page",
        "url": "https://notion.so/test",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-01-02T00:00:00Z",
        # These should be removed
        "text": "page content",
        "blocks": [{"type": "paragraph", "text": "hello"}],
        "truncated": False,
        "notion_internal_prop": "secret",
        "api_secret_key": "xxx",
    }

    result = await service.get_page("abc-123")

    # Only metadata fields
    assert set(result.keys()) == {
        "page_id",
        "title",
        "url",
        "created_time",
        "last_edited_time",
    }


@pytest.mark.asyncio
async def test_get_page_client_error_propagated(mock_client, settings_with_allowlist):
    """Test client-layer errors are propagated to route."""
    service = NotionReadService(mock_client, settings_with_allowlist)

    # Mock client raising error
    mock_client.get_page.side_effect = NotionMCPExecutionError("Notion API error")

    with pytest.raises(NotionMCPExecutionError, match="Notion API error"):
        await service.get_page("abc-123")


@pytest.mark.asyncio
async def test_normalize_page_id_removes_dashes():
    """Test _normalize_page_id removes dashes."""
    service = NotionReadService(AsyncMock(), Settings())

    assert service._normalize_page_id("abc-123") == "abc123"
    assert service._normalize_page_id("abc123") == "abc123"
    assert service._normalize_page_id("  abc-123  ") == "abc123"


@pytest.mark.asyncio
async def test_is_page_id_allowed_checks_normalization():
    """Test allowlist check uses normalized IDs."""
    service = NotionReadService(
        AsyncMock(),
        Settings(
            notion_allowed_page_ids=["abc-123", "xyz-789"],
        ),
    )

    # Should match after normalization
    assert service._is_page_id_allowed("abc-123") is True
    assert service._is_page_id_allowed("abc123") is True
    assert service._is_page_id_allowed("xyz-789") is True
    assert service._is_page_id_allowed("xyz789") is True

    # Should not match
    assert service._is_page_id_allowed("def-456") is False
