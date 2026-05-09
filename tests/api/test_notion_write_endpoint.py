from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.notion_write import write_page, write_row
from app.main import app
from app.schemas.notion_write import NotionPageWriteIn, NotionRowWriteIn
from app.services.notion_write import (
    NotionWriteBlockedError,
    NotionWriteExecutionError,
    NotionWriteValidationError,
)


class _FakeResult:
    def __init__(self, operation: str, target_type: str, target_id: str, notion_object_id: str, status: str, request_id: str) -> None:
        self.operation = operation
        self.target_type = target_type
        self.target_id = target_id
        self.notion_object_id = notion_object_id
        self.status = status
        self.request_id = request_id


class _FakeService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def write_page(self, page_id: str, updates: dict, request_id=None):
        if self._error:
            raise self._error
        return self._result

    async def create_row(self, database_id: str, properties: dict, request_id=None):
        if self._error:
            raise self._error
        return self._result

    async def update_row(self, database_id: str, row_id: str, updates: dict, request_id=None):
        if self._error:
            raise self._error
        return self._result


def test_notion_write_routes_are_registered() -> None:
    assert any(route.path == "/notion-write/page" for route in app.routes)
    assert any(route.path == "/notion-write/row" for route in app.routes)


@pytest.mark.asyncio
async def test_write_page_returns_200() -> None:
    result = await write_page(
        NotionPageWriteIn(page_id="page-123", updates={"status": "done"}),
        service=_FakeService(
            result=_FakeResult(
                operation="page_update",
                target_type="page",
                target_id="page-123",
                notion_object_id="page-123",
                status="success",
                request_id="req-1",
            )
        ),
    )

    assert result.model_dump() == {
        "operation": "page_update",
        "target_type": "page",
        "target_id": "page-123",
        "notion_object_id": "page-123",
        "status": "success",
        "request_id": "req-1",
    }


@pytest.mark.asyncio
async def test_write_row_returns_200_for_create() -> None:
    result = await write_row(
        NotionRowWriteIn(
            operation="create",
            database_id="db-123",
            properties={"Name": "Task", "Status": "done"},
        ),
        service=_FakeService(
            result=_FakeResult(
                operation="row_create",
                target_type="database",
                target_id="db-123",
                notion_object_id="row-123",
                status="success",
                request_id="req-2",
            )
        ),
    )

    assert result.model_dump()["operation"] == "row_create"
    assert result.model_dump()["status"] == "success"


@pytest.mark.asyncio
async def test_write_page_maps_blocked_error_to_403() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await write_page(
            NotionPageWriteIn(page_id="page-123", updates={"status": "done"}),
            service=_FakeService(error=NotionWriteBlockedError("not in allowlist")),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_write_page_maps_validation_error_to_422() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await write_page(
            NotionPageWriteIn(page_id="page-123", updates={"status": "invalid"}),
            service=_FakeService(error=NotionWriteValidationError("invalid payload")),
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_write_page_maps_execution_error_to_502() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await write_page(
            NotionPageWriteIn(page_id="page-123", updates={"status": "done"}),
            service=_FakeService(error=NotionWriteExecutionError("upstream failed")),
        )

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_write_row_update_requires_row_id() -> None:
    with pytest.raises(ValueError, match="row_id is required"):
        NotionRowWriteIn(
            operation="update",
            database_id="db-123",
            properties={"status": "done"},
        )
