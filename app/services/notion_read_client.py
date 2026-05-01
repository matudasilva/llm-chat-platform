"""
MCP-based Notion Read client with lifecycle management and error taxonomy.

Responsibilities:
- Spawn and manage notion-mcp-read subprocess via MCP stdio protocol
- Execute hardcoded tool allowlist (notion_get_page only, MVP)
- Separate errors by layer: timeout, protocol, execution
- Enforce timeout per request
- Minimal response validation (extract needed fields only)

MCP SDK wiring (mcp>=1.27.0):
  stdio_client(params)                     # context manager → yields (read_stream, write_stream)
  ClientSession(read_stream, write_stream) # context manager → yields session (self), starts receive_loop
  await session.initialize()               # MCP handshake before any call_tool()
"""

import asyncio
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)


class NotionMCPError(Exception):
    """Base exception for MCP client layer errors."""
    pass


class NotionMCPTimeoutError(NotionMCPError):
    """MCP request timeout."""
    pass


class NotionMCPProtocolError(NotionMCPError):
    """MCP subprocess or protocol error."""
    pass


class NotionMCPExecutionError(NotionMCPError):
    """Notion API error from MCP server."""
    pass


class ControlledNotionReadClient:
    """
    Process-level MCP client for notion-mcp-read subprocess.

    Lifecycle: started once at app startup via app.lifespan(), shared singleton.
    Tool allowlist: hardcoded to notion_get_page only (no dynamic discovery).

    Internal state after start():
      _stdio_cm   : the stdio_client context manager (keeps subprocess alive)
      _session_cm : the ClientSession context manager (runs receive_loop task)
      _session    : the ClientSession instance (ready for call_tool after initialize)
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 10.0,
    ):
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.timeout_s = timeout_s
        self._stdio_cm = None   # stdio_client context manager
        self._session_cm: ClientSession | None = None  # ClientSession (also a ctx mgr)
        self._session: ClientSession | None = None     # entered session
        self._started = False

    async def start(self) -> None:
        """
        Spawn MCP subprocess, build ClientSession, and run MCP handshake.

        Raises:
            NotionMCPProtocolError: if subprocess fails to start or handshake fails
        """
        if self._started:
            logger.warning("ControlledNotionReadClient already started, skipping")
            return

        try:
            logger.info(
                "Starting notion-mcp-read subprocess: %s %s",
                self.command, " ".join(self.args),
            )

            params = StdioServerParameters(
                command=self.command,
                args=self.args,
                cwd=self.cwd,
            )

            # Step 1: enter stdio_client → get (read_stream, write_stream)
            self._stdio_cm = stdio_client(params)
            read_stream, write_stream = await self._stdio_cm.__aenter__()

            # Step 2: build ClientSession from streams; enter it → starts receive_loop
            self._session_cm = ClientSession(read_stream, write_stream)
            self._session = await self._session_cm.__aenter__()

            # Step 3: MCP handshake (must happen before call_tool)
            await self._session.initialize()

            self._started = True
            logger.info("notion-mcp-read subprocess started and MCP session initialized")

        except Exception as e:
            # Clean up partially-entered contexts in reverse order
            if self._session_cm is not None:
                try:
                    await self._session_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            if self._stdio_cm is not None:
                try:
                    await self._stdio_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            self._started = False
            self._session = None
            self._session_cm = None
            self._stdio_cm = None
            raise NotionMCPProtocolError(f"Failed to start MCP subprocess: {e}") from e

    async def stop(self) -> None:
        """Graceful shutdown: exit ClientSession, then stdio subprocess."""
        if not self._started:
            return

        logger.info("Stopping notion-mcp-read subprocess")
        self._started = False

        # Exit in reverse order of entry
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.error("Error exiting ClientSession: %s", e)

        if self._stdio_cm is not None:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.error("Error exiting stdio_client: %s", e)

        self._session = None
        self._session_cm = None
        self._stdio_cm = None

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """
        Call notion_get_page tool via MCP (hardcoded tool allowlist).

        Args:
            page_id: Notion page ID

        Returns:
            Raw MCP response dict with page metadata

        Raises:
            NotionMCPTimeoutError: if request times out
            NotionMCPProtocolError: if MCP protocol or subprocess error
            NotionMCPExecutionError: if Notion API error or invalid response
        """
        if not self._started or self._session is None:
            raise NotionMCPProtocolError("MCP client not started")

        try:
            logger.debug("Calling notion_get_page page_id=%s", page_id)
            result = await asyncio.wait_for(
                self._session.call_tool("notion_get_page", {"page_id": page_id}),
                timeout=self.timeout_s,
            )

            # Extract JSON from first text content block
            if result.content:
                for block in result.content:
                    if block.type == "text":
                        try:
                            data = json.loads(block.text)
                            logger.debug("Received page data keys=%s", list(data.keys()))
                            return data
                        except json.JSONDecodeError as e:
                            raise NotionMCPExecutionError(
                                f"Invalid JSON response from MCP: {e}"
                            ) from e

            raise NotionMCPExecutionError("Empty or invalid MCP response")

        except asyncio.TimeoutError as e:
            raise NotionMCPTimeoutError(
                f"MCP request timeout after {self.timeout_s}s"
            ) from e
        except NotionMCPError:
            raise
        except Exception as e:
            msg = str(e).lower()
            if "protocol" in msg or "subprocess" in msg:
                raise NotionMCPProtocolError(str(e)) from e
            raise NotionMCPExecutionError(f"MCP error: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """Diagnostics only — not used for /readyz."""
        if not self._started:
            return {"status": "not_started", "ready": False}
        return {"status": "ready", "ready": True}
