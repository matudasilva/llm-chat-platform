from __future__ import annotations

import json
from typing import Any

import httpx


class NotionWriteClientError(Exception):
    """Base error for Notion write client failures."""


class NotionWriteTransportError(NotionWriteClientError):
    """Raised when the Notion API request cannot be completed."""


class NotionWriteResponseError(NotionWriteClientError):
    """Raised when the Notion API response is invalid or unexpected."""


class NotionWriteClient:
    def __init__(
        self,
        *,
        api_token: str | None,
        base_url: str = "https://api.notion.com/v1",
        api_version: str = "2026-03-11",
        timeout_s: float = 10.0,
    ) -> None:
        self._api_token = api_token.strip() if isinstance(api_token, str) else None
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        if not self._api_token:
            raise NotionWriteTransportError("Notion API token is required")
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Notion-Version": self._api_version,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_s,
                headers=self._headers(),
            ) as client:
                response = await client.request(method, path, json=payload)
        except httpx.HTTPStatusError as exc:
            detail: str | None = None
            try:
                body = exc.response.text.strip()
                if body:
                    detail = body
            except Exception:
                detail = None
            suffix = f": {detail}" if detail else ""
            raise NotionWriteTransportError(
                f"Notion API returned {exc.response.status_code}{suffix}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise NotionWriteTransportError("Notion API request timed out") from exc
        except httpx.HTTPError as exc:
            raise NotionWriteTransportError(str(exc)) from exc

        if response.status_code >= 400:
            detail: str | None = None
            try:
                body = response.text.strip()
                if body:
                    detail = body
            except Exception:
                detail = None
            suffix = f": {detail}" if detail else ""
            raise NotionWriteTransportError(f"Notion API returned {response.status_code}{suffix}")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise NotionWriteResponseError("Notion API response was not valid JSON") from exc

        if not isinstance(data, dict):
            raise NotionWriteResponseError("Notion API response must be a JSON object")
        return data

    async def update_page(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    async def create_row(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/pages",
            {"parent": {"data_source_id": database_id}, "properties": properties},
        )

    async def update_row(self, row_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self.update_page(row_id, properties)
