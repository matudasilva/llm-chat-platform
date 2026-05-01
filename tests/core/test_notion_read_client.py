"""
Tests for ControlledNotionReadClient MCP lifecycle and tool execution.

Strategy: Mock both stdio_client and ClientSession so no subprocess is spawned.

MCP SDK wiring verified by these tests:
  stdio_client(params)            # yields (read_stream, write_stream) via __aenter__
  ClientSession(rs, ws).__aenter__ → session  (starts receive_loop, returns self)
  session.initialize()             # MCP handshake
  session.call_tool(...)           # tool invocation
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notion_read_client import (
    ControlledNotionReadClient,
    NotionMCPExecutionError,
    NotionMCPProtocolError,
    NotionMCPTimeoutError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stdio_cm(enter_exc=None):
    """
    Simulate stdio_client context manager.
    __aenter__ yields (read_stream, write_stream).
    """
    cm = MagicMock()
    mock_rs, mock_ws = MagicMock(), MagicMock()
    if enter_exc:
        cm.__aenter__ = AsyncMock(side_effect=enter_exc)
    else:
        cm.__aenter__ = AsyncMock(return_value=(mock_rs, mock_ws))
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, mock_rs, mock_ws


def _make_session(initialize_exc=None):
    """
    Simulate ClientSession instance: async ctx manager that returns itself from __aenter__.
    ClientSession.__aenter__ starts a receive_loop and returns self.
    """
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    if initialize_exc:
        session.initialize = AsyncMock(side_effect=initialize_exc)
    else:
        session.initialize = AsyncMock()
    session.call_tool = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_start_success():
    """
    Correct wiring: stdio_client.__aenter__ yields (rs, ws);
    ClientSession(rs, ws).__aenter__ starts receive_loop and returns session;
    session.initialize() is called for MCP handshake.
    """
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    stdio_cm, _, _ = _make_stdio_cm()
    mock_session = _make_session()

    with (
        patch("app.services.notion_read_client.stdio_client", return_value=stdio_cm),
        patch("app.services.notion_read_client.ClientSession", return_value=mock_session),
    ):
        await client.start()

    assert client._started is True
    assert client._session is mock_session
    mock_session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_start_stdio_failure():
    """OSError from subprocess spawn → NotionMCPProtocolError."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    stdio_cm, _, _ = _make_stdio_cm(enter_exc=OSError("binary not found"))

    with patch("app.services.notion_read_client.stdio_client", return_value=stdio_cm):
        with pytest.raises(NotionMCPProtocolError, match="Failed to start MCP subprocess"):
            await client.start()

    assert client._started is False
    assert client._session is None


@pytest.mark.asyncio
async def test_client_start_initialize_failure():
    """initialize() failure → NotionMCPProtocolError; both contexts cleaned up."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    stdio_cm, _, _ = _make_stdio_cm()
    mock_session = _make_session(initialize_exc=RuntimeError("handshake failed"))

    with (
        patch("app.services.notion_read_client.stdio_client", return_value=stdio_cm),
        patch("app.services.notion_read_client.ClientSession", return_value=mock_session),
    ):
        with pytest.raises(NotionMCPProtocolError, match="Failed to start MCP subprocess"):
            await client.start()

    assert client._started is False
    assert client._session is None
    mock_session.__aexit__.assert_awaited()
    stdio_cm.__aexit__.assert_awaited()


@pytest.mark.asyncio
async def test_client_stop_success():
    """stop() exits session context then stdio context."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    stdio_cm, _, _ = _make_stdio_cm()
    mock_session = _make_session()

    with (
        patch("app.services.notion_read_client.stdio_client", return_value=stdio_cm),
        patch("app.services.notion_read_client.ClientSession", return_value=mock_session),
    ):
        await client.start()

    await client.stop()

    assert client._started is False
    assert client._session is None
    mock_session.__aexit__.assert_awaited()
    stdio_cm.__aexit__.assert_awaited()


@pytest.mark.asyncio
async def test_client_stop_already_stopped():
    """stop() on non-started client is a safe no-op."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    await client.stop()
    assert client._started is False


# ---------------------------------------------------------------------------
# get_page tests (bypass start() by injecting internal state directly)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_page_success():
    """Successful get_page returns parsed JSON from first MCP text content block."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)

    response_data = {
        "page_id": "abc123",
        "title": "Test Page",
        "url": "https://notion.so/test",
    }
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = json.dumps(response_data)

    mock_result = MagicMock()
    mock_result.content = [content_block]

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    client._session = mock_session
    client._started = True

    result = await client.get_page("abc123")

    assert result == response_data
    mock_session.call_tool.assert_awaited_once_with(
        "notion_get_page", {"page_id": "abc123"}
    )


@pytest.mark.asyncio
async def test_get_page_timeout():
    """asyncio.TimeoutError → NotionMCPTimeoutError."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=0.01)

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())
    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPTimeoutError, match="timeout"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_not_started():
    """get_page before start() raises NotionMCPProtocolError."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)

    with pytest.raises(NotionMCPProtocolError, match="not started"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_empty_response():
    """Empty content list → NotionMCPExecutionError."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)

    mock_result = MagicMock()
    mock_result.content = []

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPExecutionError, match="Empty or invalid"):
        await client.get_page("abc123")


@pytest.mark.asyncio
async def test_get_page_invalid_json():
    """Non-JSON text content → NotionMCPExecutionError."""
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)

    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = "not valid json {"

    mock_result = MagicMock()
    mock_result.content = [content_block]

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    client._session = mock_session
    client._started = True

    with pytest.raises(NotionMCPExecutionError, match="Invalid JSON response"):
        await client.get_page("abc123")


# ---------------------------------------------------------------------------
# health_check tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_started():
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)
    client._started = True
    client._session = MagicMock()

    result = await client.health_check()
    assert result == {"status": "ready", "ready": True}


@pytest.mark.asyncio
async def test_health_check_not_started():
    client = ControlledNotionReadClient(command="notion-mcp-read", timeout_s=10.0)

    result = await client.health_check()
    assert result == {"status": "not_started", "ready": False}
