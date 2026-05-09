# Notion Write Safety Analysis

**ORQ-15 Task 3 Deliverable**

Analysis of Notion API write operations to establish safe boundaries for future Notion Write MVP (ORQ-16).

**Scope:** Page property updates, database row operations, database property updates, and cross-operation scenarios.

**Status:** Safety analysis complete, ready for Execution Review.

---

## 1. Executive Summary

This document categorizes 8 common Notion write operations by safety tier and documents:
- Safe operations (metadata, reversible, low risk)
- Risk operations (structural, audit-required, high impact)
- Forbidden operations (destructive, out of scope)
- Mitigation strategies for each

**Key Finding:** Notion API supports safe metadata updates (page properties, database rows) with proper allowlisting. Structural changes (database schema) and content modification (page blocks) remain high-risk and deferred to Phase 2.

---

## 2. Scope Clarification

**Covered in this analysis:**
- Individual page property updates (page metadata)
- Database row operations (create, update field values)
- Database property updates (add/modify fields)
- Cross-operation scenarios (page in database relations)

**Explicitly out of scope (Phase 2+):**
- Page block content (text, rich text editing)
- Page deletion
- Database deletion
- Real-time collaboration
- Permission/role changes

---

## 3. Operations Matrix

| # | Operation | API | Type | Safety | Risk Level | Allowed in MVP? | Mitigation |
|---|-----------|-----|------|--------|------------|-----------------|-----------|
| 1 | Update page properties | `PATCH /v1/pages/{id}` | Page metadata | ✅ Safe | Low | YES | Allowlist page ID; validate field names; type check |
| 2 | Create database row | `POST /v1/pages` (in database) | Row create | ⚠️ Risk | Medium | **YES (with conditions)** | Allowlist database ID; enforce template schema; validate all required fields |
| 3 | Update row field values | `PATCH /v1/pages/{id}` (row) | Row update | ✅ Safe | Low | YES | Allowlist row page ID; validate field names; type check |
| 4 | Add database property | `PATCH /v1/databases/{id}` | DB schema | ⚠️ Risk | High | NO | Requires admin approval; deferred to Phase 2 |
| 5 | Modify database property | `PATCH /v1/databases/{id}` | DB schema | ⚠️ Risk | High | NO | Requires admin approval; deferred to Phase 2 |
| 6 | Delete page | `DELETE /v1/pages/{id}` | Destructive | ❌ Forbidden | Critical | NO | Destructive; never allowed (use archive instead) |
| 7 | Update page blocks | `PATCH /v1/blocks/{id}` | Content | ❌ Forbidden | Critical | NO | Text editing too risky; deferred to Phase 2 |

**Pre-Flight Validation (Helper Operations):**

| # | Operation | API | Purpose | Allowed? | Notes |
|---|-----------|-----|---------|----------|-------|
| A | Query database | `POST /v1/databases/{id}/query` | Lookup rows before update | ✅ YES | Used to check if row exists, get row page_id, validate state |
| B | Read page | `GET /v1/pages/{id}` | Get current page state | ✅ YES | Used for audit trail, conflict detection |

---

## 4. Detailed Analysis by Operation

### Operation 1: Update Page Properties (✅ Safe)

**API:** `PATCH /v1/pages/{id}`

**Description:**
Update metadata properties of an individual page (title, select fields, date fields, checkbox, etc.).

**Example:**
```json
{
  "properties": {
    "Status": { "select": { "name": "Done" } },
    "Last Updated": { "date": { "start": "2026-05-08" } }
  }
}
```

**Why Safe:**
- Metadata only (no text content)
- Reversible (updates can be undone)
- Bounded scope (single page, defined fields)
- Low blast radius (no cascade effects)

**Risk Factors:**
- If allowlist is missing, unauthorized pages could be modified
- If field types aren't validated, API could reject request (non-destructive failure)

**Mitigation:**
1. **Allowlist enforcement:** Check page ID against `NOTION_ALLOWED_PAGE_IDS` before any update
2. **Field validation:** Only allow updates to fields in `editable_fields` schema
3. **Type validation:** Validate update value matches field type (enum values, date format, etc.)
4. **Audit logging:** Log every update with request_id, page_id, fields changed, timestamp
5. **No retry on type error:** If validation fails, return 422 immediately (don't retry)

**Example Allowed Update:**
```json
{
  "page_id": "page_abc123def456",                   // Allowlist verified (example ID)
  "properties": {
    "status": { "select": { "name": "done" } }     // Field in editable_fields
  }
}
// Result: ✅ 200 OK, update succeeds
```

**Example Forbidden Update:**
```json
{
  "page_id": "unauthorized-page-id",               // NOT in allowlist
  "properties": {
    "status": { "select": { "name": "done" } }
  }
}
// Result: ❌ 403 Forbidden, "Page not in allowlist"
```

---

### Operation 2: Create Database Row (⚠️ Risk — Allowed with Strict Conditions)

**API:** `POST /v1/pages`

**Description:**
Create a new page as a row in a database (not a standalone page).

**Example:**
```json
{
  "parent": { "database_id": "allowed-database-id" },
  "properties": {
    "Name": { "title": [{ "text": { "content": "New Task" } }] },
    "Status": { "select": { "name": "todo" } }
  }
}
```

**Why Risk (but Allowed):**
- Creates new data (not just updating existing)
- Database structure must be known in advance
- Bulk row creation could bloat database

**Conditions for Allowance:**
1. **Database MUST be in allowlist:** Explicit per-database approval (not "any database")
2. **Template MUST be enforced:** Only fields from `NOTION_DATABASE_TEMPLATES[database_id]` allowed
3. **Required fields MUST be present:** Template specifies which fields are mandatory
4. **Field types MUST match:** Validate each property against database schema
5. **Row count governance:** (Phase 2) Rate limiting or quota per database

**Risk Factors (if conditions not met):**
- Unauthorized database access (if not allowlisted)
- Data bloat (rows created without template governance)
- Type mismatch with database fields
- Orphaned rows (rows created in wrong database)

**Mitigation:**
1. **Database allowlist:** Only allow row creation in explicitly listed databases (config: `NOTION_ALLOWED_DATABASES`)
2. **Template enforcement:** Define schema per database (config: `NOTION_DATABASE_TEMPLATES`)
   - Example: `NOTION_DATABASE_TEMPLATES["database-id"] = {"Name": "title", "Status": "select", ...}`
3. **Required field validation:** Check that all mandatory fields are present and valid
4. **Type validation:** Validate each property matches database field type
5. **Audit logging:** Log every row creation with database_id, created_row_id, field values, timestamp
6. **Rate limiting:** (Phase 2) Prevent row-creation DoS (e.g., 10 rows/min per database)

**Example Allowed Row Create:**
```json
{
  "database_id": "allowed-database-id",            // Database allowlisted
  "properties": {
    "Name": "New Task",                            // Required field present
    "Status": "todo"                               // Valid enum value
  }
}
// Result: ✅ 200 OK, row created with id
```

**Example Forbidden Row Create:**
```json
{
  "database_id": "unauthorized-database-id",       // NOT in allowlist
  "properties": {
    "Name": "New Task"
  }
}
// Result: ❌ 403 Forbidden, "Database not in allowlist"
```

---

### Operation 3: Update Row Field Values (✅ Safe)

**API:** `PATCH /v1/pages/{id}` (where id is a row page)

**Description:**
Update field values in an existing database row (same as Operation 1, but for rows).

**Example:**
```json
{
  "properties": {
    "Status": { "select": { "name": "In Progress" } },
    "Priority": { "select": { "name": "High" } }
  }
}
```

**Why Safe:**
- Same as Operation 1 (metadata only, reversible, bounded)
- Row already exists, no data creation
- Field types are database-defined

**Risk Factors:**
- Unauthorized row access
- Invalid field type

**Mitigation:**
1. **Row allowlist:** Check row page ID against allowlist
2. **Field validation:** Only allow fields in `editable_fields`
3. **Type validation:** Validate against database field schema
4. **Audit logging:** Log all updates

---

### Operation 4: Add Database Property (⚠️ Risk — Forbidden in MVP)

**API:** `PATCH /v1/databases/{id}`

**Description:**
Add a new property/column to a database schema.

**Example:**
```json
{
  "properties": {
    "Custom Field": {
      "type": "number",
      "number": { "format": "dollar" }
    }
  }
}
```

**Why Risk/Forbidden:**
- Modifies database structure (all rows affected)
- Requires understanding of Notion schema versioning
- Breaking change potential (if code expects old schema)
- High audit impact

**Mitigation:**
- **Deferred to Phase 2:** Requires explicit admin approval, governance process
- **Not in MVP:** Too risky without proper change management

---

### Operation 5: Modify Database Property (⚠️ Risk — Forbidden in MVP)

**API:** `PATCH /v1/databases/{id}`

**Description:**
Modify an existing database property (change field type, options, etc.).

**Why Risk/Forbidden:**
- May lose data (e.g., convert number → select)
- Breaks code expectations
- Complex conflict resolution with existing rows

**Mitigation:**
- **Deferred to Phase 2:** Requires admin approval + migration strategy

---

### Operation 6: Delete Page (❌ Forbidden — Never)

**API:** `DELETE /v1/pages/{id}`

**Description:**
Permanently delete a page.

**Why Forbidden:**
- Destructive (cannot be undone by API)
- High risk of accidental data loss
- Audit nightmare

**Mitigation:**
- **Never allow in any ORQ:** Archive instead (set status property to "Archived")

---

### Operation 7: Update Page Blocks (❌ Forbidden — Phase 2+)

**API:** `PATCH /v1/blocks/{id}`

**Description:**
Modify page content (text, rich text, code blocks, etc.).

**Why Forbidden in MVP:**
- Modifies page text/content (not just metadata)
- Notion block structure is complex
- High risk of rendering issues
- Requires full block-level understanding

**Mitigation:**
- **Deferred to Phase 2:** Once safety model for blocks is established

---

### Operation 8: Query Database (✅ Safe — Read-Only)

**API:** `POST /v1/databases/{id}/query`

**Description:**
Query a database with filters, sorts, pagination.

**Why Safe:**
- Read-only (no modification)
- Already supported by Notion Read (ORQ-14)

**Note:**
- Allows read-only inspection of database rows
- Useful for validation (check if row exists before update)
- No special allowlist needed (same as `/notion-read/page`)

---

## 5. Allowlist Design

### Structure (Pages + Database Rows)

**Configuration (in `.env` or config):**

```yaml
NOTION_WRITE_ENABLED: true

# Individual pages that can be edited
NOTION_ALLOWED_PAGES:
  - "page_abc123def456"                  # Page 1 (editable, example ID)
  - "page_xyz789ghi012"                  # Page 2 (editable, example ID)

# Databases where rows can be created
NOTION_ALLOWED_DATABASES:
  - "xyz789abc123def456ghi789jkl012"    # Database 1 (row creation allowed)
  - "pqr456stu789vwx012yza345bcd678"    # Database 2 (row creation allowed)

# Editable fields per resource (page or database)
NOTION_EDITABLE_FIELDS:
  # Page-level editable fields
  "page_id_1":
    "status": ["todo", "in_progress", "done"]     # Enum with valid options
    "priority": ["low", "medium", "high"]
    "tags": {}                                     # Multi-select (any values)
    "due_date": {}                                 # Date type
    "completed": {}                                # Checkbox
    
  # Database-level template (for row creation)
  "database_id_1":
    # Template: fields that MUST be provided when creating a row
    "Name": { "type": "title", "required": true }
    "Status": { "type": "select", "required": true, "options": ["todo", "in_progress", "done"] }
    "Priority": { "type": "select", "required": false, "options": ["low", "medium", "high"] }
    "Assignee": { "type": "person", "required": false }
    
  # Per-row editable fields (rows in allowed databases)
  "row_in_database_id_1":
    # Subset of database fields that can be edited after row creation
    "status": ["todo", "in_progress", "done"]
    "priority": ["low", "medium", "high"]
    "assignee": {}
```

### Enforcement Rules (5-Step Validation)

**For Page Property Updates (Operation 1, 3):**

1. **Is page in allowlist?**
   ```python
   if page_id not in NOTION_ALLOWED_PAGES:
     raise 403 Forbidden("Page not in allowlist")
   ```

2. **Are all fields editable for this page?**
   ```python
   for field_name in update.keys():
     if field_name not in NOTION_EDITABLE_FIELDS[page_id]:
       raise 422 Unprocessable(f"Field '{field_name}' not editable for page")
   ```

3. **Are field values valid?**
   ```python
   for field_name, value in update.items():
     allowed_values = NOTION_EDITABLE_FIELDS[page_id][field_name]
     if field_type == "select" and value not in allowed_values:
       raise 422 Unprocessable(f"Invalid value '{value}' for field '{field_name}'")
   ```

**For Row Creation (Operation 2):**

1. **Is database in allowlist?**
   ```python
   if database_id not in NOTION_ALLOWED_DATABASES:
     raise 403 Forbidden("Database not in allowlist")
   ```

2. **Are all required template fields present?**
   ```python
   template = NOTION_DATABASE_TEMPLATES[database_id]
   for field_name, field_def in template.items():
     if field_def["required"] and field_name not in properties:
       raise 422 Unprocessable(f"Required field '{field_name}' missing")
   ```

3. **Do all properties match template schema?**
   ```python
   for field_name, value in properties.items():
     if field_name not in template:
       raise 422 Unprocessable(f"Field '{field_name}' not in template for this database")
     if not validate_field_type(field_name, value, template[field_name]):
       raise 422 Unprocessable(f"Invalid type/value for field '{field_name}'")
   ```

**For Row Field Updates (Operation 3 — after row creation):**

1. **Is row in allowlist?** (check row's database, then row itself)
   ```python
   row_database_id = get_row_database(row_page_id)  # Query Notion to determine parent database
   if row_database_id not in NOTION_ALLOWED_DATABASES:
     raise 403 Forbidden("Row's database not in allowlist")
   ```

2. **Are all fields editable for this row?**
   ```python
   editable_per_database = NOTION_EDITABLE_FIELDS[f"row_in_{row_database_id}"]
   for field_name in update.keys():
     if field_name not in editable_per_database:
       raise 422 Unprocessable(f"Field '{field_name}' not editable for rows in this database")
   ```

3. **Are field values valid?**
   ```python
   # Same validation as page updates (enum checks, type validation, etc.)
   ```

---

## 6. Error Taxonomy (5+ Scenarios)

| # | Error | HTTP Code | Root Cause | Mitigation | Example |
|---|-------|-----------|-----------|-----------|---------|
| 1 | Page not in allowlist | 403 | Unauthorized page access attempt | Add page ID to `NOTION_ALLOWED_PAGES` | "Page 'xyz' not in allowlist" |
| 2 | Database not in allowlist | 403 | Unauthorized database access for row creation | Add database ID to `NOTION_ALLOWED_DATABASES` | "Database 'xyz' not in allowlist" |
| 3 | Field not editable | 422 | Field not in `NOTION_EDITABLE_FIELDS` | Add field to editable fields config | "Field 'internal_id' not editable for page 'xyz'" |
| 4 | Invalid field value | 422 | Value not in allowed enum or wrong type | Check field schema; use valid enum value | "Invalid value 'pending' for status (allowed: todo, in_progress, done)" |
| 5 | Field type mismatch | 422 | Field type doesn't match schema | Check Notion database schema; send correct type | "Field 'count' expects number, got string" |
| 6 | Notion API error (downstream) | 502 | Notion API returned error | Check Notion status page; retry if transient | "Notion API returned 429 (rate limited)" |

---

## 7. Validation Rules (Pseudo-Code)

**Rule 1: is_page_in_allowlist(page_id) → bool**
```
function is_page_in_allowlist(page_id):
  return page_id in NOTION_ALLOWED_PAGES
  
Example: is_page_in_allowlist("page_abc123def456") → True  # Example ID
```

**Rule 2: is_database_in_allowlist(database_id) → bool**
```
function is_database_in_allowlist(database_id):
  return database_id in NOTION_ALLOWED_DATABASES
  
Example: is_database_in_allowlist("xyz789abc123def456ghi789jkl012") → True
```

**Rule 3: is_field_editable(resource_id, field_name) → bool**
```
function is_field_editable(resource_id, field_name):
  if resource_id not in NOTION_EDITABLE_FIELDS:
    return False
  return field_name in NOTION_EDITABLE_FIELDS[resource_id]
  
Example: is_field_editable("page_abc123", "status") → True
         is_field_editable("page_abc123", "internal_id") → False
         is_field_editable("row_in_database_xyz", "priority") → True
```

**Rule 4: validate_field_value(field_name, value, field_schema) → ValidationResult**
```
function validate_field_value(field_name, value, field_schema):
  field_type = field_schema["type"]
  
  if field_type == "select":
    allowed_options = field_schema.get("options", [])
    if value not in allowed_options:
      return ValidationResult(False, f"Invalid value '{value}' (allowed: {allowed_options})")
  
  if field_type == "date":
    if not is_valid_iso8601(value):
      return ValidationResult(False, f"Invalid date format: {value}")
  
  if field_type == "number":
    if not is_number(value):
      return ValidationResult(False, f"Invalid number: {value}")
  
  return ValidationResult(True, "")
  
Example: validate_field_value("status", "done", {"type": "select", "options": ["todo", "in_progress", "done"]}) → ValidationResult(True, "")
         validate_field_value("status", "invalid", {"type": "select", "options": ["todo", "in_progress"]}) → ValidationResult(False, "Invalid value...")
```

**Rule 5: validate_page_write(page_id, updates) → ValidationResult**
```
function validate_page_write(page_id, updates):
  if not is_page_in_allowlist(page_id):
    return ValidationResult(False, "Page not in allowlist")
  
  for field_name, value in updates.items():
    if not is_field_editable(page_id, field_name):
      return ValidationResult(False, f"Field '{field_name}' not editable for this page")
    
    field_schema = get_field_schema(page_id, field_name)
    field_validation = validate_field_value(field_name, value, field_schema)
    if not field_validation.is_valid:
      return field_validation
  
  return ValidationResult(True, "")
  
Example: validate_page_write("abc123", {"status": "done"}) → ValidationResult(True, "")
         validate_page_write("xyz999", {"status": "done"}) → ValidationResult(False, "Page not in allowlist")
```

**Rule 6: validate_row_create(database_id, properties) → ValidationResult**
```
function validate_row_create(database_id, properties):
  if not is_database_in_allowlist(database_id):
    return ValidationResult(False, "Database not in allowlist")
  
  template = NOTION_DATABASE_TEMPLATES[database_id]
  
  # Check required fields
  for field_name, field_def in template.items():
    if field_def["required"] and field_name not in properties:
      return ValidationResult(False, f"Required field '{field_name}' missing")
  
  # Validate all provided fields
  for field_name, value in properties.items():
    if field_name not in template:
      return ValidationResult(False, f"Field '{field_name}' not in template for this database")
    
    field_schema = template[field_name]
    field_validation = validate_field_value(field_name, value, field_schema)
    if not field_validation.is_valid:
      return field_validation
  
  return ValidationResult(True, "")
  
Example: validate_row_create("db_xyz", {"Name": "New Task", "Status": "todo"}) → ValidationResult(True, "")
         validate_row_create("db_xyz", {"Status": "todo"}) → ValidationResult(False, "Required field 'Name' missing")
```

---

## 8. Implementation Roadmap

**ORQ-15 (this):** Safety analysis + validator skeleton (no execution)
- [x] Identify safe operations (1, 3, 8)
- [x] Identify risk operations (2, 4, 5)
- [x] Identify forbidden operations (6, 7)
- [x] Document allowlist design
- [x] Document validation rules (pseudo-code)
- [ ] Task 6: Implement `NotionWriteValidator` (skeleton, no MCP calls)
- [ ] Task 7: Unit tests (100% coverage, no API calls)

**ORQ-16 (future):** Notion Write MVP
- Implement write execution (MCP integration)
- Add user/role authorization (depends on ORQ-15 safety contract)
- Add audit logging
- Add rate limiting
- Validate against safety analysis

---

## 9. Questions Resolved

**Q: Should we cover page properties only or also database rows?**
A: **Both** (Option B). This analysis covers:
- Individual page property updates (safe)
- Database row operations (conditional, with allowlist)
- Database schema changes (risk, deferred)

**Q: When is Notion Write MVP ready to implement?**
A: After ORQ-15 closure, safety contract is locked. ORQ-16 can proceed with write execution, respecting all mitigation strategies documented here.

---

## 10. Deferred (Phase 2+)

- Database schema management (add/modify properties)
- Page block content editing
- Page deletion (archive instead)
- Real-time collaboration patterns
- Role-based access control (RBAC)
- Rate limiting and quota enforcement

---

**Analysis complete. Ready for Execution Review.**

**Evidence:** This document (`docs/notion_write_safety_analysis.md`)  
**Status:** Task 3 deliverable for ORQ-15  
**Next:** Tasks 4-8 (allowlist design, validation rules, validator skeleton, tests, documentation)
