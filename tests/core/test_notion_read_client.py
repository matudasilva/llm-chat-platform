"""
Tests for ControlledNotionReadClient MCP lifecycle and tool execution.

Strategy: Mock subprocess communication, test lifecycle, error handling.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notion_read_client import (
    ControlledNotionReadClient,
    NotionMCPError,
    NotionMCPExecutionError,
    NotionMCPProtocolError,
    NotionMCPTimeoutError,
)


@pytest.mark.asyncio
async def test_client_start_success():
    """Test successful client startup."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock stdio_client context manager
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None

    with patch("app.services.notion_read_client.stdio_client", return_value=mock_cm):
        await client.start()

    assert client._started is True
    assert client._session is mock_session


@pytest.mark.asyncio
async def test_client_start_failure():
    """Test client startup failure raises NotionMCPProtocolError."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock stdio_client raising exception
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = RuntimeError("subprocess failed")

    with patch("app.services.notion_read_client.stdio_client", return_value=mock_cm):
        with pytest.raises(NotionMCPProtocolError, match="Failed to start MCP subprocess"):
            await client.start()

    assert client._started is False


@pytest.mark.asyncio
async def test_client_stop_success():
    """Test graceful client shutdown."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock startup first
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None

    with patch("app.services.notion_read_client.stdio_client", return_value=mock_cm):
        await client.start()

    # Now test stop
    await client.stop()

    assert client._started is False
    mock_cm.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_client_stop_already_stopped():
    """Test stop on non-started client is safe."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Should not raise
    await client.stop()
    assert client._started is False


@pytest.mark.asyncio
async def test_get_page_success():
    """Test successful get_page call."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock response
    response_data = {
        "page_id": "abc123",
        "title": "Test Page",
        "url": "https://notion.so/test",
    }
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = json.dumps(response_data)

    mock_result = MagicMock()
    mock_result.content = [mock_content]

    # Mock session
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    client._session = mock_session
    client._started = True

    result = await client.get_page("abc123")

    assert result == response_data
    mock_session.call_tool.assert_called_once_with(
        "notion_get_page",
        {"page_id": "abc123"},
    )


@pytest.mark.asyncio
async def test_get_page_timeout():
    """Test get_page timeout raises NotionMCPTimeoutError."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=0.01,  # Very short timeout
    )

    # Mock session that times out
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPTimeoutError, match="timeout"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_not_started():
    """Test get_page on non-started client raises NotionMCPProtocolError."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    with pytest.raises(NotionMCPProtocolError, match="not started"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_empty_response():
    """Test get_page with empty response raises NotionMCPExecutionError."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock empty response
    mock_result = MagicMock()
    mock_result.content = []

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPExecutionError, match="Empty or invalid"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_invalid_json():
    """Test get_page with invalid JSON response raises NotionMCPExecutionError."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock invalid JSON response
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "not valid json"

    mock_result = MagicMock()
    mock_result.content = [mock_content]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPExecutionError, match="Invalid JSON response"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_health_check_success():
    """Test health check on started client."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    # Mock started client
    mock_session = AsyncMock()
    client._session = mock_session
    client._started = True

    result = await client.health_check()

    assert result["status"] == "ready"
    assert result["ready"] is True


@pytest.mark.asyncio
async def test_health_check_not_started():
    """Test health check on non-started client."""
    client = ControlledNotionReadClient(
        command="notion-mcp-read",
        args=[],
        cwd=None,
        timeout_s=10.0,
    )

    result = await client.health_check()

    assert result["status"] == "not_started"
    assert result["ready"] is False
