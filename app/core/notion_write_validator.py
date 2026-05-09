"""
Notion Write Safety Validator

Static validation of Notion write operations before execution.
NO MCP calls, NO Notion API interaction.
ORQ-15 Task 6 deliverable.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
import re


@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    explanation: str = ""

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)

    def __str__(self) -> str:
        if self.is_valid:
            return "✅ Valid"
        return f"❌ Invalid: {'; '.join(self.errors)}"


class NotionWriteValidator:
    """
    Validator for Notion write operations.

    Validates write payloads against allowlist and schema before execution.
    No network calls, deterministic validation only.
    """

    def __init__(
        self,
        allowed_pages: Optional[List[str]] = None,
        allowed_databases: Optional[List[str]] = None,
        editable_fields: Optional[Dict[str, Dict[str, Any]]] = None,
        database_templates: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Initialize validator with configuration.

        Args:
            allowed_pages: List of page IDs that can be edited
            allowed_databases: List of database IDs where rows can be created
            editable_fields: Dict mapping resource ID to editable field names and allowed values
            database_templates: Dict mapping database ID to row creation template schema
        """
        self.allowed_pages = set(allowed_pages or [])
        self.allowed_databases = set(allowed_databases or [])
        self.editable_fields = editable_fields or {}
        self.database_templates = database_templates or {}

    # ========== Rule 1: Page in Allowlist ==========

    def is_page_in_allowlist(self, page_id: str) -> bool:
        """Check if page ID is in allowlist."""
        return page_id in self.allowed_pages

    def validate_page_id(self, page_id: str) -> ValidationResult:
        """Validate that a page ID is in allowlist."""
        if not page_id:
            return ValidationResult(False, errors=["Page ID cannot be empty"])
        if not self.is_page_in_allowlist(page_id):
            return ValidationResult(
                False,
                errors=[f"Page '{page_id}' not in allowlist"],
                explanation="Add page ID to NOTION_ALLOWED_PAGES config",
            )
        return ValidationResult(True, explanation="Page in allowlist")

    # ========== Rule 2: Database in Allowlist ==========

    def is_database_in_allowlist(self, database_id: str) -> bool:
        """Check if database ID is in allowlist."""
        return database_id in self.allowed_databases

    def validate_database_id(self, database_id: str) -> ValidationResult:
        """Validate that a database ID is in allowlist."""
        if not database_id:
            return ValidationResult(False, errors=["Database ID cannot be empty"])
        if not self.is_database_in_allowlist(database_id):
            return ValidationResult(
                False,
                errors=[f"Database '{database_id}' not in allowlist"],
                explanation="Add database ID to NOTION_ALLOWED_DATABASES config",
            )
        return ValidationResult(True, explanation="Database in allowlist")

    # ========== Rule 3: Field Editable ==========

    def is_field_editable(self, resource_id: str, field_name: str) -> bool:
        """Check if field is editable for a resource (page or row)."""
        if resource_id not in self.editable_fields:
            return False
        return field_name in self.editable_fields[resource_id]

    def validate_fields(self, resource_id: str, field_names: List[str]) -> ValidationResult:
        """Validate that all field names are editable for a resource."""
        if resource_id not in self.editable_fields:
            return ValidationResult(
                False,
                errors=[f"No editable fields defined for resource '{resource_id}'"],
                explanation="Add resource to NOTION_EDITABLE_FIELDS config",
            )

        invalid_fields = [f for f in field_names if not self.is_field_editable(resource_id, f)]
        if invalid_fields:
            return ValidationResult(
                False,
                errors=[f"Fields not editable: {', '.join(invalid_fields)}"],
                explanation=f"Editable fields for this resource: {list(self.editable_fields[resource_id].keys())}",
            )
        return ValidationResult(True, explanation="All fields editable")

    # ========== Rule 4: Field Value Validation ==========

    def validate_field_value(
        self, field_name: str, value: Any, field_config: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate field value against type and allowed values.

        Args:
            field_name: Name of field
            value: Value to validate
            field_config: Field schema (type, options, format, etc.)
        """
        if field_config is None:
            field_config = {}

        field_type = field_config.get("type", "string")

        # Select field: validate against options
        if field_type == "select":
            allowed_options = field_config.get("options", [])
            if allowed_options and value not in allowed_options:
                return ValidationResult(
                    False,
                    errors=[f"Invalid value '{value}' for field '{field_name}'"],
                    explanation=f"Allowed values: {allowed_options}",
                )

        # Date field: validate ISO8601 format
        elif field_type == "date":
            if not self._is_valid_iso8601(value):
                return ValidationResult(
                    False,
                    errors=[f"Invalid date format for field '{field_name}': {value}"],
                    explanation="Use ISO8601 format (YYYY-MM-DD)",
                )

        # Number field: validate numeric type
        elif field_type == "number":
            if not isinstance(value, (int, float)):
                return ValidationResult(
                    False,
                    errors=[f"Invalid number for field '{field_name}': {value}"],
                    explanation="Value must be numeric",
                )

        # Enum field: validate against options
        elif field_type == "enum":
            allowed_values = field_config.get("values", [])
            if allowed_values and value not in allowed_values:
                return ValidationResult(
                    False,
                    errors=[f"Invalid enum value '{value}' for field '{field_name}'"],
                    explanation=f"Allowed values: {allowed_values}",
                )

        return ValidationResult(True, explanation=f"Field value valid for type '{field_type}'")

    # ========== Rule 5: Page Write Validation ==========

    def validate_page_write(self, page_id: str, updates: Dict[str, Any]) -> ValidationResult:
        """
        Validate a full page write operation.

        Returns ValidationResult with combined checks:
        1. Page in allowlist
        2. All fields editable
        3. All values valid
        """
        # Step 1: Page in allowlist
        page_check = self.validate_page_id(page_id)
        if not page_check.is_valid:
            return page_check

        # Step 2: All fields editable
        field_names = list(updates.keys())
        fields_check = self.validate_fields(page_id, field_names)
        if not fields_check.is_valid:
            return fields_check

        # Step 3: Validate all field values
        for field_name, value in updates.items():
            field_config = self.editable_fields[page_id].get(field_name, {})
            value_check = self.validate_field_value(field_name, value, field_config)
            if not value_check.is_valid:
                return value_check

        return ValidationResult(True, explanation="Page write validation passed")

    # ========== Rule 6: Row Create Validation ==========

    def validate_row_create(self, database_id: str, properties: Dict[str, Any]) -> ValidationResult:
        """
        Validate a full row creation operation.

        Returns ValidationResult with combined checks:
        1. Database in allowlist
        2. All required template fields present
        3. All properties match template schema
        """
        # Step 1: Database in allowlist
        db_check = self.validate_database_id(database_id)
        if not db_check.is_valid:
            return db_check

        # Step 2: Template exists for database
        if database_id not in self.database_templates:
            return ValidationResult(
                False,
                errors=[f"No template defined for database '{database_id}'"],
                explanation="Add database to NOTION_DATABASE_TEMPLATES config",
            )

        template = self.database_templates[database_id]

        # Step 3: Check required fields
        missing_fields = []
        for field_name, field_def in template.items():
            if field_def.get("required", False) and field_name not in properties:
                missing_fields.append(field_name)

        if missing_fields:
            return ValidationResult(
                False,
                errors=[f"Required fields missing: {', '.join(missing_fields)}"],
                explanation=f"Required fields for this database: {[f for f, d in template.items() if d.get('required')]}",
            )

        # Step 4: Validate all provided properties
        for field_name, value in properties.items():
            if field_name not in template:
                return ValidationResult(
                    False,
                    errors=[f"Field '{field_name}' not in template for this database"],
                    explanation=f"Template fields: {list(template.keys())}",
                )

            field_schema = template[field_name]
            value_check = self.validate_field_value(field_name, value, field_schema)
            if not value_check.is_valid:
                return value_check

        return ValidationResult(True, explanation="Row creation validation passed")

    # ========== Rule 6b: Row Update Validation ==========

    def validate_row_update(self, row_database_id: str, row_id: str, updates: Dict[str, Any]) -> ValidationResult:
        """
        Validate a row field update operation.

        Similar to page write, but for rows in a database.
        Uses editable_fields per database (not per row).
        """
        # Step 1: Database in allowlist
        db_check = self.validate_database_id(row_database_id)
        if not db_check.is_valid:
            return db_check

        # Step 2: Row in editable set
        row_resource_id = f"row_in_{row_database_id}"
        if row_resource_id not in self.editable_fields:
            return ValidationResult(
                False,
                errors=[f"Rows in database '{row_database_id}' are not editable"],
                explanation="Add database row editable fields to config",
            )

        # Step 3: All fields editable
        field_names = list(updates.keys())
        fields_check = self.validate_fields(row_resource_id, field_names)
        if not fields_check.is_valid:
            return fields_check

        # Step 4: Validate all field values
        for field_name, value in updates.items():
            field_config = self.editable_fields[row_resource_id].get(field_name, {})
            value_check = self.validate_field_value(field_name, value, field_config)
            if not value_check.is_valid:
                return value_check

        return ValidationResult(True, explanation="Row update validation passed")

    # ========== Utility Methods ==========

    @staticmethod
    def _is_valid_iso8601(date_string: str) -> bool:
        """Check if string is valid ISO8601 date."""
        if not isinstance(date_string, str):
            return False
        try:
            # Try parsing common ISO8601 formats
            datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            return True
        except (ValueError, AttributeError):
            return False

    def get_summary(self) -> str:
        """Get summary of validator configuration."""
        return (
            f"Notion Write Validator\n"
            f"- Allowed pages: {len(self.allowed_pages)}\n"
            f"- Allowed databases: {len(self.allowed_databases)}\n"
            f"- Editable field sets: {len(self.editable_fields)}\n"
            f"- Database templates: {len(self.database_templates)}"
        )
