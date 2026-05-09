from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotionPageWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(min_length=1)
    updates: dict[str, Any] = Field(default_factory=dict)


class NotionRowWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "update"]
    database_id: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    row_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_operation_requirements(self) -> "NotionRowWriteIn":
        if self.operation == "update" and not self.row_id:
            raise ValueError("row_id is required when operation is 'update'")
        return self


class NotionWriteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["page_update", "row_create", "row_update"]
    target_type: Literal["page", "row", "database"]
    target_id: str
    notion_object_id: str | None = None
    status: Literal["success", "noop"]
    request_id: str | None = None
