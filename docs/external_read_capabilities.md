# External Read Capabilities

## Overview

The LLM Chat Platform provides two controlled, read-only external capabilities for retrieving context without invoking the main `/chat` write-path:

1. **Web Read** — Fetch and parse web page content
2. **Notion Read** — Fetch Notion page metadata

Both endpoints are **stateless, metadata-focused, and separate from `/chat`**.

---

## GET /web-read — Read Web Page Content

### Endpoint

```
GET /web-read?url=<url>
```

### Parameters

| Parameter | Type | Required | Validation |
|-----------|------|----------|-----------|
| `url` | string | Yes | min_length=1, must be a valid URL |

### Response (200 OK)

```json
{
  "url": "https://example.com",
  "final_url": "https://example.com/path",
  "content_type": "text/html; charset=utf-8",
  "title": "Page Title",
  "text": "Extracted text content...",
  "truncated": false
}
```

**Response Schema:** `WebReadOut`

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Original request URL |
| `final_url` | string | Final URL after redirects |
| `content_type` | string | MIME type of content |
| `title` | string | Page title (extracted from `<title>` or `<h1>`) |
| `text` | string | Plain text content (parsed from HTML) |
| `truncated` | boolean | True if content was truncated due to size limit |

### Status Codes

| Code | Condition | Message |
|------|-----------|---------|
| **200** | Success | Valid response with content |
| **422** | Validation Error | Missing or invalid `url` parameter |
| **403** | Forbidden | URL matches blocked domain list |
| **502** | Bad Gateway | Fetch error (network, timeout, invalid HTML) |
| **500** | Server Error | Unexpected error |

### Configuration

**Environment Variables:**

```bash
# Comma-separated list of blocked domain patterns
WEBREAD_BLOCKED_DOMAINS=ads.example.com,tracking.example.com

# Timeout for fetch operations (seconds)
WEBREAD_TIMEOUT_SECONDS=10

# Maximum content length to fetch (bytes)
WEBREAD_MAX_CONTENT_LENGTH=10485760  # 10MB

# Custom user agent
WEBREAD_USER_AGENT="LLM-Chat-Platform/1.0"
```

### Example Usage

**Request:**
```bash
curl "http://localhost:8000/web-read?url=https://example.com"
```

**Response:**
```json
{
  "url": "https://example.com",
  "final_url": "https://example.com",
  "content_type": "text/html",
  "title": "Example Domain",
  "text": "Example Domain\nThis domain is for use in examples...",
  "truncated": false
}
```

---

## GET /notion-read/page — Read Notion Page Metadata

### Endpoint

```
GET /notion-read/page?page_id=<page_id>
```

### Parameters

| Parameter | Type | Required | Validation |
|-----------|------|----------|-----------|
| `page_id` | string | Yes | min_length=1, must be a Notion page ID |

### Response (200 OK)

```json
{
  "page_id": "12345678-1234-5678-1234-567812345678",
  "title": "Page Title",
  "url": "https://www.notion.so/Page-Title-12345678",
  "created_time": "2026-05-01T10:00:00Z",
  "last_edited_time": "2026-05-08T15:30:00Z"
}
```

**Response Schema:** `NotionPageOut`

| Field | Type | Description |
|-------|------|-------------|
| `page_id` | string | Notion page ID (UUID format) |
| `title` | string | Page title |
| `url` | string | Notion page URL |
| `created_time` | string | ISO 8601 timestamp, UTC |
| `last_edited_time` | string | ISO 8601 timestamp, UTC |

### Status Codes

| Code | Condition | Message |
|------|-----------|---------|
| **200** | Success | Valid Notion page metadata |
| **422** | Validation Error | Missing or invalid `page_id` parameter |
| **403** | Forbidden | Page ID not in allowlist (access denied) |
| **502** | Bad Gateway | Notion API error or MCP protocol error |
| **504** | Gateway Timeout | MCP request timeout (upstream slow) |
| **503** | Service Unavailable | MCP subprocess unavailable (graceful degradation) |
| **500** | Server Error | Unexpected error |

### Configuration

**Environment Variables:**

```bash
# Root page ID for Notion workspace (required)
NOTION_ROOT_PAGE_ID=12345678-1234-5678-1234-567812345678

# Allowed page IDs (JSON array format)
NOTION_ALLOWED_PAGE_IDS=["page-id-1", "page-id-2", "page-id-3"]

# MCP Server command (full path to notion-mcp-read server)
NOTION_MCP_SERVER_COMMAND=node

# MCP Server arguments (JSON array format)
NOTION_MCP_SERVER_ARGS=["/path/to/notion-mcp-read/dist/server.js"]

# MCP Server working directory
NOTION_MCP_SERVER_CWD=/path/to/notion-mcp-read

# Request timeout for MCP operations (seconds)
NOTION_MCP_TIMEOUT_SECONDS=10

# Write operations disabled (forced to false)
NOTION_ENABLE_WRITE=false
```

**How to expand `NOTION_ALLOWED_PAGE_IDS`:**

1. Get the page ID from the Notion page URL: `https://www.notion.so/Page-Title-<page-id>`
2. Add to the JSON array in `.env`: `NOTION_ALLOWED_PAGE_IDS=["existing-id", "new-id"]`
3. Restart the application

### Example Usage

**Request:**
```bash
curl "http://localhost:8000/notion-read/page?page_id=12345678-1234-5678-1234-567812345678"
```

**Response:**
```json
{
  "page_id": "12345678-1234-5678-1234-567812345678",
  "title": "Meeting Notes",
  "url": "https://www.notion.so/Meeting-Notes-12345678",
  "created_time": "2026-05-01T10:00:00Z",
  "last_edited_time": "2026-05-08T15:30:00Z"
}
```

---

## Differences from `/chat`

| Aspect | `/chat` | Read Endpoints |
|--------|--------|----------------|
| Write-path | Yes (primary) | No (read-only) |
| Persistence | Yes (transactional) | No (stateless) |
| Provider Invocation | Yes (LLM API) | No (metadata only) |
| Streaming | Yes (SSE) | No (JSON response) |
| Caching | Redis cache (optional) | No caching |
| Rate Limiting | Provider-based | No rate limiting |
| State | Maintains conversations | Stateless queries |

---

## Common Patterns

### Python Requests

```python
import requests

# Web Read
response = requests.get(
    "http://localhost:8000/web-read",
    params={"url": "https://example.com"}
)
data = response.json()  # WebReadOut

# Notion Read
response = requests.get(
    "http://localhost:8000/notion-read/page",
    params={"page_id": "12345678-1234-5678-1234-567812345678"}
)
data = response.json()  # NotionPageOut
```

### JavaScript Fetch

```javascript
// Web Read
const response = await fetch(
  `http://localhost:8000/web-read?url=${encodeURIComponent(url)}`
);
const data = await response.json();

// Notion Read
const response = await fetch(
  `http://localhost:8000/notion-read/page?page_id=${pageId}`
);
const data = await response.json();
```

---

## Notes

- Both endpoints are **read-only** and do not modify any state
- Page IDs for Notion Read must be in the allowlist (configured in environment)
- Web Read respects the blocked domains configuration
- Both endpoints use structured JSON logging (correlation via `request_id`)
- Error responses include operator-friendly detail messages (no sensitive data leaked)
