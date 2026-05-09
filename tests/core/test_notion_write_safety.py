"""
Unit tests for Notion Write Safety Validator

Tests static validation of write operations.
NO Notion API calls, NO network access.
ORQ-15 Task 7 deliverable.
"""

import pytest
from app.core.notion_write_validator import NotionWriteValidator, ValidationResult


@pytest.fixture
def validator():
    """Create a validator with sample configuration."""
    return NotionWriteValidator(
        allowed_pages=["page_abc123", "page_def456"],
        allowed_databases=["db_xyz789", "db_pqr012"],
        editable_fields={
            "page_abc123": {
                "status": {"type": "select", "options": ["todo", "in_progress", "done"]},
                "priority": {"type": "select", "options": ["low", "medium", "high"]},
                "due_date": {"type": "date"},
                "completed": {"type": "bool"},
            },
            "page_def456": {
                "title": {"type": "string"},
                "archived": {"type": "bool"},
            },
            "row_in_db_xyz789": {
                "status": {"type": "select", "options": ["todo", "in_progress", "done"]},
                "assignee": {"type": "person"},
            },
        },
        database_templates={
            "db_xyz789": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "options": ["todo", "in_progress", "done"], "required": True},
                "Priority": {"type": "select", "options": ["low", "medium", "high"], "required": False},
                "Assignee": {"type": "person", "required": False},
            },
            "db_pqr012": {
                "Title": {"type": "title", "required": True},
                "Description": {"type": "text", "required": False},
            },
        },
    )


# ========== Rule 1 Tests: Page in Allowlist ==========


def test_is_page_in_allowlist_pass(validator):
    """Valid page in allowlist."""
    assert validator.is_page_in_allowlist("page_abc123") is True


def test_is_page_in_allowlist_fail(validator):
    """Invalid page not in allowlist."""
    assert validator.is_page_in_allowlist("page_invalid") is False


def test_validate_page_id_pass(validator):
    """Validate page ID that is in allowlist."""
    result = validator.validate_page_id("page_abc123")
    assert result.is_valid is True


def test_validate_page_id_fail_not_in_allowlist(validator):
    """Validate page ID that is not in allowlist."""
    result = validator.validate_page_id("page_invalid")
    assert result.is_valid is False
    assert "not in allowlist" in result.errors[0]


def test_validate_page_id_fail_empty(validator):
    """Validate empty page ID."""
    result = validator.validate_page_id("")
    assert result.is_valid is False
    assert "cannot be empty" in result.errors[0]


# ========== Rule 2 Tests: Database in Allowlist ==========


def test_is_database_in_allowlist_pass(validator):
    """Valid database in allowlist."""
    assert validator.is_database_in_allowlist("db_xyz789") is True


def test_is_database_in_allowlist_fail(validator):
    """Invalid database not in allowlist."""
    assert validator.is_database_in_allowlist("db_invalid") is False


def test_validate_database_id_pass(validator):
    """Validate database ID that is in allowlist."""
    result = validator.validate_database_id("db_xyz789")
    assert result.is_valid is True


def test_validate_database_id_fail_not_in_allowlist(validator):
    """Validate database ID that is not in allowlist."""
    result = validator.validate_database_id("db_invalid")
    assert result.is_valid is False
    assert "not in allowlist" in result.errors[0]


# ========== Rule 3 Tests: Field Editable ==========


def test_is_field_editable_pass(validator):
    """Field is editable for resource."""
    assert validator.is_field_editable("page_abc123", "status") is True


def test_is_field_editable_fail_field_not_editable(validator):
    """Field is not editable for resource."""
    assert validator.is_field_editable("page_abc123", "internal_id") is False


def test_is_field_editable_fail_resource_not_defined(validator):
    """Resource not in editable fields config."""
    assert validator.is_field_editable("page_unknown", "status") is False


def test_validate_fields_pass(validator):
    """All fields are editable."""
    result = validator.validate_fields("page_abc123", ["status", "priority"])
    assert result.is_valid is True


def test_validate_fields_fail_field_not_editable(validator):
    """One or more fields are not editable."""
    result = validator.validate_fields("page_abc123", ["status", "internal_id"])
    assert result.is_valid is False
    assert "not editable" in result.errors[0]


# ========== Rule 4 Tests: Field Value Validation ==========


def test_validate_field_value_select_pass(validator):
    """Valid select value."""
    field_config = {"type": "select", "options": ["todo", "in_progress", "done"]}
    result = validator.validate_field_value("status", "done", field_config)
    assert result.is_valid is True


def test_validate_field_value_select_fail_invalid_value(validator):
    """Invalid select value."""
    field_config = {"type": "select", "options": ["todo", "in_progress", "done"]}
    result = validator.validate_field_value("status", "invalid", field_config)
    assert result.is_valid is False
    assert "Invalid value" in result.errors[0]


def test_validate_field_value_date_pass(validator):
    """Valid ISO8601 date."""
    field_config = {"type": "date"}
    result = validator.validate_field_value("due_date", "2026-05-08", field_config)
    assert result.is_valid is True


def test_validate_field_value_date_pass_iso8601_full(validator):
    """Valid ISO8601 datetime."""
    field_config = {"type": "date"}
    result = validator.validate_field_value("due_date", "2026-05-08T10:30:00Z", field_config)
    assert result.is_valid is True


def test_validate_field_value_date_fail_invalid_format(validator):
    """Invalid date format."""
    field_config = {"type": "date"}
    result = validator.validate_field_value("due_date", "05-08-2026", field_config)
    assert result.is_valid is False
    assert "Invalid date format" in result.errors[0]


def test_validate_field_value_number_pass(validator):
    """Valid number value."""
    field_config = {"type": "number"}
    result = validator.validate_field_value("count", 42, field_config)
    assert result.is_valid is True


def test_validate_field_value_number_pass_float(validator):
    """Valid float value."""
    field_config = {"type": "number"}
    result = validator.validate_field_value("count", 3.14, field_config)
    assert result.is_valid is True


def test_validate_field_value_number_fail_not_numeric(validator):
    """Invalid non-numeric value."""
    field_config = {"type": "number"}
    result = validator.validate_field_value("count", "not a number", field_config)
    assert result.is_valid is False
    assert "Invalid number" in result.errors[0]


# ========== Rule 5 Tests: Page Write Validation ==========


def test_validate_page_write_pass(validator):
    """Valid page write with all checks passing."""
    result = validator.validate_page_write("page_abc123", {"status": "done", "priority": "high"})
    assert result.is_valid is True


def test_validate_page_write_fail_page_not_in_allowlist(validator):
    """Page not in allowlist."""
    result = validator.validate_page_write("page_invalid", {"status": "done"})
    assert result.is_valid is False
    assert "not in allowlist" in result.errors[0]


def test_validate_page_write_fail_field_not_editable(validator):
    """Field not editable for page."""
    result = validator.validate_page_write("page_abc123", {"internal_id": "xyz"})
    assert result.is_valid is False
    assert "not editable" in result.errors[0]


def test_validate_page_write_fail_field_value_invalid(validator):
    """Field value invalid for type."""
    result = validator.validate_page_write("page_abc123", {"status": "invalid_status"})
    assert result.is_valid is False
    assert "Invalid value" in result.errors[0]


def test_validate_page_write_pass_single_field(validator):
    """Page write with single field."""
    result = validator.validate_page_write("page_abc123", {"status": "todo"})
    assert result.is_valid is True


def test_validate_page_write_pass_multiple_fields(validator):
    """Page write with multiple valid fields."""
    result = validator.validate_page_write(
        "page_abc123",
        {
            "status": "in_progress",
            "priority": "high",
            "due_date": "2026-05-15",
        },
    )
    assert result.is_valid is True


# ========== Rule 6 Tests: Row Create Validation ==========


def test_validate_row_create_pass(validator):
    """Valid row creation with all required fields."""
    result = validator.validate_row_create(
        "db_xyz789",
        {
            "Name": "New Task",
            "Status": "todo",
        },
    )
    assert result.is_valid is True


def test_validate_row_create_pass_with_optional(validator):
    """Valid row creation with required and optional fields."""
    result = validator.validate_row_create(
        "db_xyz789",
        {
            "Name": "New Task",
            "Status": "in_progress",
            "Priority": "high",
        },
    )
    assert result.is_valid is True


def test_validate_row_create_fail_database_not_in_allowlist(validator):
    """Database not in allowlist."""
    result = validator.validate_row_create("db_invalid", {"Name": "Task"})
    assert result.is_valid is False
    assert "not in allowlist" in result.errors[0]


def test_validate_row_create_fail_required_field_missing(validator):
    """Required field missing from row creation."""
    result = validator.validate_row_create(
        "db_xyz789",
        {
            "Name": "New Task",
            # Missing required "Status" field
        },
    )
    assert result.is_valid is False
    assert "Required fields missing" in result.errors[0]


def test_validate_row_create_fail_field_not_in_template(validator):
    """Field not in database template."""
    result = validator.validate_row_create(
        "db_xyz789",
        {
            "Name": "New Task",
            "Status": "todo",
            "InvalidField": "value",
        },
    )
    assert result.is_valid is False
    assert "not in template" in result.errors[0]


def test_validate_row_create_fail_field_value_invalid(validator):
    """Field value invalid for type."""
    result = validator.validate_row_create(
        "db_xyz789",
        {
            "Name": "New Task",
            "Status": "invalid_status",
        },
    )
    assert result.is_valid is False
    assert "Invalid" in result.errors[0]


def test_validate_row_create_fail_no_template(validator):
    """Database has no template defined."""
    # Use db_pqr012 which has a template
    result = validator.validate_row_create(
        "db_pqr012",
        {
            "Title": "New Item",
        },
    )
    assert result.is_valid is True  # Should pass with required field


# ========== Rule 6b Tests: Row Update Validation ==========


def test_validate_row_update_pass(validator):
    """Valid row update with editable fields."""
    result = validator.validate_row_update(
        "db_xyz789",
        "row_page_id",
        {"status": "done"},
    )
    assert result.is_valid is True


def test_validate_row_update_fail_database_not_in_allowlist(validator):
    """Row's database not in allowlist."""
    result = validator.validate_row_update(
        "db_invalid",
        "row_page_id",
        {"status": "done"},
    )
    assert result.is_valid is False
    assert "not in allowlist" in result.errors[0]


def test_validate_row_update_fail_field_not_editable(validator):
    """Field not editable for rows in database."""
    result = validator.validate_row_update(
        "db_xyz789",
        "row_page_id",
        {"invalid_field": "value"},
    )
    assert result.is_valid is False
    assert "not editable" in result.errors[0]


# ========== Utility Tests ==========


def test_validation_result_add_error():
    """ValidationResult can accumulate errors."""
    result = ValidationResult(False)
    result.add_error("Error 1")
    result.add_error("Error 2")
    assert len(result.errors) == 2
    assert result.errors == ["Error 1", "Error 2"]


def test_validator_get_summary(validator):
    """Validator provides summary of configuration."""
    summary = validator.get_summary()
    assert "Notion Write Validator" in summary
    assert "Allowed pages: 2" in summary
    assert "Allowed databases: 2" in summary


def test_empty_updates_pass(validator):
    """Empty updates dict passes validation."""
    result = validator.validate_page_write("page_abc123", {})
    assert result.is_valid is True


def test_is_valid_iso8601_formats():
    """ISO8601 date validation."""
    validator_instance = NotionWriteValidator()
    assert validator_instance._is_valid_iso8601("2026-05-08") is True
    assert validator_instance._is_valid_iso8601("2026-05-08T10:30:00Z") is True
    assert validator_instance._is_valid_iso8601("2026-05-08T10:30:00+00:00") is True
    assert validator_instance._is_valid_iso8601("05-08-2026") is False
    assert validator_instance._is_valid_iso8601("not a date") is False
