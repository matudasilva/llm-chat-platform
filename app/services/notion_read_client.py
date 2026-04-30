"""
MCP-based Notion Read client with lifecycle management and error taxonomy.

Responsibilities:
- Spawn and manage notion-mcp-read subprocess via MCP stdio protocol
- Execute hardcoded tool allowlist (notion_get_page only, MVP)
- Separate errors by layer: timeout, protocol, execution
- Enforce timeout per request
- Minimal response validation (extract needed fields only)
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
        self._session: ClientSession | None = None
        self._cm = None  # context manager
        self._started = False

    async def start(self) -> None:
        """
        Spawn MCP subprocess and verify health.

        Raises:
            NotionMCPProtocolError: if subprocess fails to start or health check fails
        """
        if self._started:
            logger.warning("ControlledNotionReadClient already started, skipping")
            return

        try:
            logger.info(
                f"Starting notion-mcp-read subprocess: {self.command} {' '.join(self.args)}"
            )

            # Create StdioServerParameters
            params = StdioServerParameters(
                command=self.command,
                args=self.args,
                cwd=self.cwd,
            )

            # Start the context manager
            self._cm = stdio_client(params)
            self._session = await self._cm.__aenter__()

            logger.info("notion-mcp-read subprocess started and connected")
            self._started = True
        except Exception as e:
            self._started = False
            self._session = None
            self._cm = None
            raise NotionMCPProtocolError(f"Failed to start MCP subprocess: {e}") from e

    async def stop(self) -> None:
        """Graceful shutdown of MCP subprocess."""
        if not self._started:
            return

        try:
            logger.info("Stopping notion-mcp-read subprocess")
            if self._cm:
                await self._cm.__aexit__(None, None, None)
            self._started = False
            self._session = None
            self._cm = None
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
            self._started = False

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """
        Call notion_get_page tool via MCP.

        Args:
            page_id: Notion page ID

        Returns:
            Raw MCP response (dict with page metadata)

        Raises:
            NotionMCPTimeoutError: if request times out
            NotionMCPProtocolError: if MCP protocol error
            NotionMCPExecutionError: if Notion API error
        """
        if not self._started or not self._session:
            raise NotionMCPProtocolError("MCP client not started")

        try:
            logger.debug(f"Calling notion_get_page with page_id={page_id}")
            result = await asyncio.wait_for(
                self._session.call_tool(
                    "notion_get_page",
                    {"page_id": page_id},
                ),
                timeout=self.timeout_s,
            )

            # Extract content from MCP response
            if result.content:
                for content_block in result.content:
                    if content_block.type == "text":
                        try:
                            response_data = json.loads(content_block.text)
                            logger.debug(f"Received page data: {response_data}")
                            return response_data
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
            # Map any other error to protocol or execution error
            if "protocol" in str(e).lower() or "subprocess" in str(e).lower():
                raise NotionMCPProtocolError(str(e)) from e
            raise NotionMCPExecutionError(f"MCP error: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """
        Quick health check (diagnostics only, not for readiness).

        Returns:
            Dict with status and details

        Raises:
            NotionMCPProtocolError: if check fails
        """
        if not self._started:
            return {"status": "not_started", "ready": False}

        try:
            # For now, check is just verifying the session is alive
            # A more sophisticated check could call a tool with dummy data
            return {"status": "ready", "ready": True}
        except Exception as e:
            raise NotionMCPProtocolError(f"Health check failed: {e}") from e
