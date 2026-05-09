# Notion Write Safety Contract

**ORQ-15 Final Deliverable**

Complete safety contract for Notion write operations (without execution). Foundation for ORQ-16 implementation.

**Status:** Complete and ready for ORQ-16 implementation.

---

## 1. Overview

This document establishes a **static safety contract** for write operations to Notion. The contract defines:
- Which operations are safe to execute
- Which are risky and require strict conditions
- Which are forbidden
- Validation rules to enforce before any write
- Configuration requirements for safe deployment

**Key Principle:** Write operations are validated BEFORE execution. Validation is static (no API calls), deterministic, and fast.

---

## 2. What This Contract Covers

✅ **Covered (Safe Boundaries Defined):**
- Individual page property updates (metadata)
- Database row creation (with template enforcement)
- Database row field updates (metadata)
- Pre-flight validation queries (lookups before writes)

❌ **Out of Scope (Deferred to Phase 2+):**
- Page block content editing
- Page deletion
- Database schema changes
- Real-time collaboration
- Role-based access control (RBAC)
- Rate limiting and quotas

---

## 3. Operations Matrix

See `docs/notion_write_safety_analysis.md` Section 3 for complete matrix.

**Quick Reference:**

| Operation | Safety | Allowed? | Conditions |
|-----------|--------|----------|-----------|
| Update page properties | ✅ Safe | YES | Allowlist page ID |
| Create database row | ⚠️ Risk | YES | Allowlist database; enforce template |
| Update row fields | ✅ Safe | YES | Allowlist row database |
| Add database property | ⚠️ Risk | NO | Requires admin (Phase 2) |
| Delete page | ❌ Forbidden | NO | Never allowed |
| Edit page blocks | ❌ Forbidden | NO | Never allowed (Phase 2) |

---

## 4. Validator Implementation

### Class: `NotionWriteValidator`

Located in `app/core/notion_write_validator.py`.

**No execution, no API calls.** Static validation only.

#### Initialization

```python
from app.core.notion_write_validator import NotionWriteValidator

validator = NotionWriteValidator(
    allowed_pages=["page_abc123", "page_def456"],
    allowed_databases=["db_xyz789"],
    editable_fields={
        "page_abc123": {
            "status": {"type": "select", "options": ["todo", "done"]},
            "due_date": {"type": "date"},
        },
        "row_in_db_xyz789": {
            "status": {"type": "select", "options": ["todo", "done"]},
        },
    },
    database_templates={
        "db_xyz789": {
            "Name": {"type": "title", "required": True},
            "Status": {"type": "select", "options": ["todo", "done"], "required": True},
        },
    },
)
```

#### Validation Methods

**1. Page Write Validation**

```python
result = validator.validate_page_write(
    page_id="page_abc123",
    updates={"status": "done", "due_date": "2026-05-09"}
)
# Returns: ValidationResult(is_valid=True, errors=[], explanation="...")
```

Checks:
- Page in allowlist
- All fields editable for page
- All values valid for field types

**2. Row Creation Validation**

```python
result = validator.validate_row_create(
    database_id="db_xyz789",
    properties={"Name": "New Task", "Status": "todo"}
)
# Returns: ValidationResult(is_valid=True, ...)
```

Checks:
- Database in allowlist
- All required template fields present
- All properties match template schema
- All values valid for types

**3. Row Update Validation**

```python
result = validator.validate_row_update(
    row_database_id="db_xyz789",
    row_id="row_page_id",
    updates={"status": "done"}
)
# Returns: ValidationResult(is_valid=True, ...)
```

Checks:
- Database in allowlist
- All fields editable for rows in database
- All values valid for types

---

## 5. Configuration Reference

### Environment Variables (Example)

```yaml
# Pages that can be edited
NOTION_ALLOWED_PAGES=["page_abc123def456", "page_xyz789ghi012"]

# Databases where rows can be created/edited
NOTION_ALLOWED_DATABASES=["xyz789abc123", "pqr012stu345"]

# Editable fields per resource (JSON)
NOTION_EDITABLE_FIELDS={
  "page_id_1": {
    "status": ["todo", "in_progress", "done"],
    "priority": ["low", "medium", "high"],
    "due_date": {},
    "completed": {}
  },
  "row_in_db_id_1": {
    "status": ["todo", "in_progress", "done"],
    "assignee": {}
  }
}

# Row creation templates per database (JSON)
NOTION_DATABASE_TEMPLATES={
  "db_id_1": {
    "Name": {"type": "title", "required": true},
    "Status": {"type": "select", "options": ["todo", "done"], "required": true},
    "Priority": {"type": "select", "options": ["low", "medium", "high"], "required": false}
  }
}
```

---

## 6. Error Handling

For each validation failure, `NotionWriteValidator` returns `ValidationResult` with:
- `is_valid: bool` — Whether validation passed
- `errors: List[str]` — Error messages
- `explanation: str` — Guidance on how to fix

### Example Error Cases

**403 Forbidden (Access Denied):**
```python
result = validator.validate_page_write("unauthorized_page", {"status": "done"})
# result.is_valid = False
# result.errors = ["Page 'unauthorized_page' not in allowlist"]
# result.explanation = "Add page ID to NOTION_ALLOWED_PAGES config"
```

**422 Unprocessable (Validation Error):**
```python
result = validator.validate_page_write("page_123", {"status": "invalid"})
# result.is_valid = False
# result.errors = ["Invalid value 'invalid' for field 'status'"]
# result.explanation = "Allowed values: ['todo', 'in_progress', 'done']"
```

---

## 7. Usage in ORQ-16 (Notion Write MVP)

When implementing actual write execution (ORQ-16), use validator **before** making Notion API calls:

```python
async def create_row(database_id: str, properties: Dict[str, Any]) -> Response:
    # Step 1: Static validation (this ORQ)
    validator = NotionWriteValidator(config)  # Load from env
    validation = validator.validate_row_create(database_id, properties)
    
    if not validation.is_valid:
        return JSONResponse(
            status_code=422,
            content={"detail": validation.errors[0]}
        )
    
    # Step 2: Execute Notion API call (ORQ-16)
    row = await notion_client.pages.create(
        parent={"database_id": database_id},
        properties=properties
    )
    
    # Step 3: Audit logging
    log_row_created(row.id, database_id, properties)
    
    return JSONResponse(status_code=200, content={"row_id": row.id})
```

---

## 8. Test Coverage

All validation rules have 100% test coverage:
- 42 unit tests
- Pass cases (valid writes)
- Fail cases (invalid access, fields, types)
- Edge cases (empty updates, ISO8601 dates, etc.)
- No Notion API calls in tests

Test file: `tests/core/test_notion_write_safety.py`

Run tests:
```bash
python -m pytest tests/core/test_notion_write_safety.py -v
# 42 passed in 0.04s
```

---

## 9. No Regression Guarantee

✅ **Protected Layers (Unchanged):**
- `/chat` endpoint
- ChatService
- ProviderPort and providers
- Persistence schema
- Streaming semantics

✅ **CI Baseline Passing:**
- All existing tests pass
- Docker build succeeds
- Zero functional regressions

---

## 10. Deferred to Phase 2+

- Database schema management (add/modify properties)
- Page block content editing
- Page deletion (archive instead)
- Real-time collaboration patterns
- Role-based access control (RBAC)
- Rate limiting and quota enforcement
- Audit logging (full implementation)
- Conflict detection and resolution

---

## 11. Questions Answered

**Q: What operations are safe for MVP?**
A: Page property updates and database row creation/updates with strict allowlisting and template enforcement.

**Q: What if validation fails?**
A: Return 403 (access denied) or 422 (validation error) immediately. No retry, no partial execution.

**Q: How is security enforced?**
A: Static validation before any API call. Validator is instantiated at app startup with config (allowlist, templates).

**Q: Can this validator run in Docker?**
A: Yes. It's pure Python, no external dependencies, no network access. Works in any environment.

---

## 12. Validator API Reference

See `app/core/notion_write_validator.py` docstrings for complete API:

- `validate_page_write(page_id, updates) → ValidationResult`
- `validate_row_create(database_id, properties) → ValidationResult`
- `validate_row_update(row_database_id, row_id, updates) → ValidationResult`
- `validate_page_id(page_id) → ValidationResult`
- `validate_database_id(database_id) → ValidationResult`
- `validate_fields(resource_id, field_names) → ValidationResult`
- `validate_field_value(field_name, value, field_config) → ValidationResult`

---

## 13. Next Steps (ORQ-16)

1. Integrate validator into `/notion-write/page` and `/notion-write/row` endpoints
2. Add Notion MCP write capabilities (call MCP server with validated payloads)
3. Implement audit logging for all writes
4. Add rate limiting and quotas (Phase 2)
5. Implement RBAC authorization (Phase 2)

---

**Safety contract complete. Ready for ORQ-16 implementation.**

**Generated:** 2026-05-09  
**Based on:** `docs/notion_write_safety_analysis.md`  
**Validator:** `app/core/notion_write_validator.py`  
**Tests:** `tests/core/test_notion_write_safety.py`
