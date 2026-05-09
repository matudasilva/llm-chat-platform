from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.notion_write_validator import NotionWriteValidator, ValidationResult
from app.core.settings import Settings, settings
from app.http.request_context import get_request_id
from app.services.notion_write_client import NotionWriteClient

logger = logging.getLogger(__name__)


class NotionWriteError(Exception):
    """Base exception for Notion write service failures."""


class NotionWriteDisabledError(NotionWriteError):
    """Raised when Notion writes are disabled in settings."""


class NotionWriteBlockedError(NotionWriteError):
    """Raised when an allowlist check fails."""


class NotionWriteValidationError(NotionWriteError):
    """Raised when a payload fails static validation."""


class NotionWriteExecutionError(NotionWriteError):
    """Raised when the external Notion write call fails."""


@dataclass(frozen=True)
class NotionWriteResult:
    operation: str
    target_type: str
    target_id: str
    notion_object_id: str | None
    status: str
    request_id: str | None = None


def _normalize_id(value: str) -> str:
    return value.strip().replace("-", "")


def _validate_or_raise(result: ValidationResult) -> None:
    if not result.is_valid:
        message = result.errors[0] if result.errors else result.explanation or "validation failed"
        if "allowlist" in message.lower() or "not in allowlist" in message.lower():
            raise NotionWriteBlockedError(message)
        raise NotionWriteValidationError(message)


class NotionWriteService:
    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        client: NotionWriteClient | None = None,
        validator: NotionWriteValidator | None = None,
    ) -> None:
        self._settings = app_settings
        self._validator = validator or NotionWriteValidator(
            allowed_pages=app_settings.notion_allowed_page_ids,
            allowed_databases=app_settings.notion_allowed_database_ids,
            editable_fields=app_settings.notion_editable_fields,
            database_templates=app_settings.notion_database_templates,
        )
        self._client = client or NotionWriteClient(
            api_token=app_settings.notion_api_token,
            base_url=app_settings.notion_api_base_url,
            api_version=app_settings.notion_api_version,
            timeout_s=app_settings.notion_write_timeout_s,
        )

    def _ensure_enabled(self) -> None:
        if not self._settings.notion_write_enabled:
            raise NotionWriteDisabledError("Notion write is disabled")

    def _audit(self, *, operation: str, target_type: str, target_id: str, status: str, field_names: list[str], request_id: str | None) -> None:
        payload = {
            "event": "notion.write",
            "operation": operation,
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
            "field_names": field_names,
            "request_id": request_id,
        }
        try:
            logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    def _field_schema(self, schema_by_field: dict[str, Any], field_name: str) -> dict[str, Any]:
        return dict(schema_by_field.get(field_name, {}))

    @staticmethod
    def _notion_property_key(field_name: str, field_config: dict[str, Any]) -> str:
        explicit_key = (
            field_config.get("notion_property_key")
            or field_config.get("property_key")
            or field_config.get("notion_name")
            or field_config.get("property_name")
            or field_config.get("notion_property_name")
        )
        if isinstance(explicit_key, str) and explicit_key.strip():
            return explicit_key.strip()
        return field_name

    @staticmethod
    def _serialize_value(field_name: str, value: Any, field_config: dict[str, Any]) -> dict[str, Any]:
        field_type = str(field_config.get("type", "string")).lower()
        notion_field_name = NotionWriteService._notion_property_key(field_name, field_config)

        if field_type == "title":
            return {notion_field_name: {"title": [{"text": {"content": str(value)}}]}}
        if field_type in {"string", "text", "rich_text"}:
            return {notion_field_name: {"rich_text": [{"text": {"content": str(value)}}]}}
        if field_type in {"select", "enum"}:
            return {notion_field_name: {"select": {"name": str(value)}}}
        if field_type == "status":
            return {notion_field_name: {"status": {"name": str(value)}}}
        if field_type == "multi_select":
            values = value if isinstance(value, list) else [value]
            return {
                notion_field_name: {
                    "multi_select": [{"name": str(item)} for item in values if str(item).strip()]
                }
            }
        if field_type == "date":
            return {notion_field_name: {"date": {"start": str(value)}}}
        if field_type == "number":
            return {notion_field_name: {"number": value}}
        if field_type in {"bool", "checkbox"}:
            return {notion_field_name: {"checkbox": bool(value)}}
        if field_type == "person":
            people = value if isinstance(value, list) else [value]
            return {
                notion_field_name: {
                    "people": [{"id": str(item)} for item in people if str(item).strip()]
                }
            }
        if field_type == "url":
            return {notion_field_name: {"url": str(value)}}
        if field_type == "email":
            return {notion_field_name: {"email": str(value)}}
        if field_type == "phone_number":
            return {notion_field_name: {"phone_number": str(value)}}
        return {notion_field_name: {"rich_text": [{"text": {"content": str(value)}}]}}

    def _build_properties_payload(self, schema_by_field: dict[str, Any], field_values: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name, value in field_values.items():
            field_config = self._field_schema(schema_by_field, field_name)
            payload.update(self._serialize_value(field_name, value, field_config))
        return payload

    async def write_page(self, page_id: str, updates: dict[str, Any], *, request_id: str | None = None) -> NotionWriteResult:
        self._ensure_enabled()
        normalized_page_id = _normalize_id(page_id)
        normalized_request_id = request_id or get_request_id()
        field_names = list(updates.keys())

        self._audit(
            operation="page_update",
            target_type="page",
            target_id=normalized_page_id,
            status="attempt",
            field_names=field_names,
            request_id=normalized_request_id,
        )

        _validate_or_raise(self._validator.validate_page_id(normalized_page_id))
        _validate_or_raise(self._validator.validate_fields(normalized_page_id, field_names))

        for field_name, value in updates.items():
            _validate_or_raise(
                self._validator.validate_field_value(
                    field_name,
                    value,
                    self._field_schema(self._validator.editable_fields.get(normalized_page_id, {}), field_name),
                )
            )

        if not updates:
            self._audit(
                operation="page_update",
                target_type="page",
                target_id=normalized_page_id,
                status="noop",
                field_names=[],
                request_id=normalized_request_id,
            )
            return NotionWriteResult(
                operation="page_update",
                target_type="page",
                target_id=page_id,
                notion_object_id=page_id,
                status="noop",
                request_id=normalized_request_id,
            )

        try:
            response = await self._client.update_page(
                page_id=page_id,
                properties=self._build_properties_payload(
                    self._validator.editable_fields.get(normalized_page_id, {}),
                    updates,
                ),
            )
        except Exception as exc:
            self._audit(
                operation="page_update",
                target_type="page",
                target_id=normalized_page_id,
                status="error",
                field_names=field_names,
                request_id=normalized_request_id,
            )
            raise NotionWriteExecutionError(str(exc)) from exc

        notion_object_id = str(response.get("id") or page_id)
        self._audit(
            operation="page_update",
            target_type="page",
            target_id=normalized_page_id,
            status="success",
            field_names=field_names,
            request_id=normalized_request_id,
        )
        return NotionWriteResult(
            operation="page_update",
            target_type="page",
            target_id=page_id,
            notion_object_id=notion_object_id,
            status="success",
            request_id=normalized_request_id,
        )

    async def create_row(self, database_id: str, properties: dict[str, Any], *, request_id: str | None = None) -> NotionWriteResult:
        self._ensure_enabled()
        normalized_database_id = _normalize_id(database_id)
        normalized_request_id = request_id or get_request_id()
        field_names = list(properties.keys())

        self._audit(
            operation="row_create",
            target_type="database",
            target_id=normalized_database_id,
            status="attempt",
            field_names=field_names,
            request_id=normalized_request_id,
        )

        _validate_or_raise(self._validator.validate_database_id(normalized_database_id))
        _validate_or_raise(self._validator.validate_row_create(normalized_database_id, properties))

        try:
            response = await self._client.create_row(
                database_id=database_id,
                properties=self._build_properties_payload(
                    self._validator.database_templates.get(normalized_database_id, {}),
                    properties,
                ),
            )
        except Exception as exc:
            self._audit(
                operation="row_create",
                target_type="database",
                target_id=normalized_database_id,
                status="error",
                field_names=field_names,
                request_id=normalized_request_id,
            )
            raise NotionWriteExecutionError(str(exc)) from exc

        notion_object_id = str(response.get("id") or "")
        self._audit(
            operation="row_create",
            target_type="database",
            target_id=normalized_database_id,
            status="success",
            field_names=field_names,
            request_id=normalized_request_id,
        )
        return NotionWriteResult(
            operation="row_create",
            target_type="database",
            target_id=database_id,
            notion_object_id=notion_object_id or None,
            status="success",
            request_id=normalized_request_id,
        )

    async def update_row(
        self,
        database_id: str,
        row_id: str,
        updates: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> NotionWriteResult:
        self._ensure_enabled()
        normalized_database_id = _normalize_id(database_id)
        normalized_request_id = request_id or get_request_id()
        field_names = list(updates.keys())

        self._audit(
            operation="row_update",
            target_type="row",
            target_id=row_id,
            status="attempt",
            field_names=field_names,
            request_id=normalized_request_id,
        )

        _validate_or_raise(self._validator.validate_database_id(normalized_database_id))
        _validate_or_raise(self._validator.validate_row_update(normalized_database_id, row_id, updates))

        if not updates:
            self._audit(
                operation="row_update",
                target_type="row",
                target_id=row_id,
                status="noop",
                field_names=[],
                request_id=normalized_request_id,
            )
            return NotionWriteResult(
                operation="row_update",
                target_type="row",
                target_id=row_id,
                notion_object_id=row_id,
                status="noop",
                request_id=normalized_request_id,
            )

        try:
            response = await self._client.update_row(
                row_id=row_id,
                properties=self._build_properties_payload(
                    self._validator.editable_fields.get(f"row_in_{normalized_database_id}", {}),
                    updates,
                ),
            )
        except Exception as exc:
            self._audit(
                operation="row_update",
                target_type="row",
                target_id=row_id,
                status="error",
                field_names=field_names,
                request_id=normalized_request_id,
            )
            raise NotionWriteExecutionError(str(exc)) from exc

        notion_object_id = str(response.get("id") or row_id)
        self._audit(
            operation="row_update",
            target_type="row",
            target_id=row_id,
            status="success",
            field_names=field_names,
            request_id=normalized_request_id,
        )
        return NotionWriteResult(
            operation="row_update",
            target_type="row",
            target_id=row_id,
            notion_object_id=notion_object_id,
            status="success",
            request_id=normalized_request_id,
        )


def get_notion_write_service() -> NotionWriteService:
    return NotionWriteService(settings)
