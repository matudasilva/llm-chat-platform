"""
Domain service for Notion Read with allowlist enforcement and response sanitization.

Responsibilities:
- Orchestrate ControlledNotionReadClient + Settings
- Enforce page_id allowlist (MVP only, no database_ids)
- Normalize page IDs (remove dashes for consistent comparison)
- Sanitize responses to metadata-only fields
- Separate service-layer errors from client-layer errors
"""

import logging
from typing import Any

from app.core.settings import Settings
from app.services.notion_read_client import (
    ControlledNotionReadClient,
    NotionMCPError,
)

logger = logging.getLogger(__name__)


class NotionReadError(Exception):
    """Base exception for service-layer Notion Read errors."""

    pass


class NotionReadBlockedError(NotionReadError):
    """Page ID not in allowlist."""

    pass


class NotionReadService:
    """
    Domain service for Notion Read.

    Orchestrates MCP client + settings, enforces allowlist, sanitizes responses.
    """

    def __init__(self, client: ControlledNotionReadClient, settings: Settings):
        self.client = client
        self.settings = settings

    @staticmethod
    def _normalize_page_id(page_id: str) -> str:
        """Normalize page ID by removing dashes."""
        return page_id.strip().replace("-", "")

    def _is_page_id_allowed(self, page_id: str) -> bool:
        """Check if page_id is in allowlist (after normalization)."""
        if not self.settings.notion_allowed_page_ids:
            logger.warning("No page IDs in allowlist, denying access")
            return False

        normalized = self._normalize_page_id(page_id)
        allowed_normalized = [
            self._normalize_page_id(pid) for pid in self.settings.notion_allowed_page_ids
        ]

        is_allowed = normalized in allowed_normalized
        if not is_allowed:
            logger.warning(f"Page ID {page_id} not in allowlist")
        return is_allowed

    def _sanitize_response(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """
        Sanitize response to metadata-only fields.

        Keeps: page_id, title, url, created_time, last_edited_time
        Removes: text, blocks, truncated, internal Notion fields
        """
        metadata_fields = [
            "page_id",
            "title",
            "url",
            "created_time",
            "last_edited_time",
        ]

        sanitized = {}
        for field in metadata_fields:
            if field in raw_response:
                sanitized[field] = raw_response[field]

        logger.debug(f"Sanitized response to metadata fields: {list(sanitized.keys())}")
        return sanitized

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """
        Get page metadata from Notion via MCP client.

        Args:
            page_id: Notion page ID (with or without dashes)

        Returns:
            Sanitized metadata dict

        Raises:
            NotionReadBlockedError: page_id not in allowlist
            NotionReadError: other service-layer errors
            NotionMCPError: propagated client-layer errors (caught by route)
        """
        # Check allowlist first
        if not self._is_page_id_allowed(page_id):
            raise NotionReadBlockedError(
                f"Page ID not in allowlist: {self._normalize_page_id(page_id)}"
            )

        try:
            logger.info(f"Fetching page via MCP: {page_id}")
            raw_response = await self.client.get_page(page_id)

            # Sanitize response
            sanitized = self._sanitize_response(raw_response)
            logger.debug(f"Page fetched and sanitized: {sanitized}")

            return sanitized

        except NotionMCPError:
            # Re-raise client-layer errors (route will map to HTTP status)
            raise
        except Exception as e:
            # Unexpected error
            logger.error(f"Error fetching page: {e}")
            raise NotionReadError(f"Error fetching page: {e}") from e
