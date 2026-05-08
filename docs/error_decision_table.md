# Error Decision Table — External Read Endpoints

## Overview

This document maps HTTP status codes to root causes, operator actions, and example logs for both external read endpoints.

---

## Error Decision Matrix

| Status | Endpoint(s) | Root Cause | Operator Action | Expected Log | Mitigation |
|--------|------------|-----------|-----------------|--------------|-----------|
| **200** | Both | Success | None | `{"status": 200, "latency_ms": N}` | N/A |
| **403** | Web Read | URL in blocked domains | Remove from `WEBREAD_BLOCKED_DOMAINS` or request domain unblock | `{"level": "WARNING", "message": "Access denied"}` | Update `.env` and restart |
| **403** | Notion Read | Page ID not in allowlist | Add page ID to `NOTION_ALLOWED_PAGE_IDS` | `{"level": "WARNING", "message": "Page blocked by allowlist"}` | Update `.env` and restart |
| **422** | Both | Missing or invalid parameter | Provide required parameter (non-empty string) | `{"status": 422, "detail": "field required"}` | Correct the request |
| **502** | Web Read | Network error, fetch failure, invalid HTML, upstream error | Check target URL reachability; increase timeout if needed | `{"level": "ERROR", "message": "Failed to fetch"}` | Verify target URL works; adjust `WEBREAD_TIMEOUT_SECONDS` |
| **502** | Notion Read | Notion API error, MCP protocol error, upstream failure | Check Notion API status; verify MCP server logs | `{"level": "ERROR", "message": "MCP protocol error"}` | Verify MCP server running; check Notion API credentials |
| **503** | Notion Read | MCP subprocess unavailable | Restart application (MCP will auto-spawn) | `{"level": "ERROR", "message": "Notion Read service unavailable"}` | `docker compose restart api` |
| **504** | Notion Read | Upstream timeout (Notion API slow) | Increase timeout; check upstream status | `{"level": "WARNING", "message": "MCP timeout"}` | Increase `NOTION_MCP_TIMEOUT_SECONDS`; retry later |
| **500** | Both | Unexpected server error | Check application logs; restart if needed | `{"level": "ERROR", "message": "Unexpected error", "traceback": "..."}` | Check logs; contact support if persistent |

---

## Decision Logic by Error Code

### 200 OK — Success

**Path:** Request → Valid parameter → Upstream responds → Return data

**Example logs:**
```json
{
  "request_id": "req-001",
  "path": "/web-read",
  "method": "GET",
  "status": 200,
  "latency_ms": 234
}
```

**Operator action:** None required.

---

### 403 Forbidden — Access Denied

**Decision tree:**
```
Is page_id in NOTION_ALLOWED_PAGE_IDS?
├─ No → Return 403 "Page blocked by allowlist"
└─ Yes → (Should not reach 403)

Is URL in WEBREAD_BLOCKED_DOMAINS?
├─ Yes → Return 403 "Access denied: URL blocked"
└─ No → (Should not reach 403)
```

**Example logs (Notion):**
```json
{
  "request_id": "req-002",
  "path": "/notion-read/page",
  "status": 403,
  "latency_ms": 10
}
{
  "level": "WARNING",
  "message": "Page blocked by allowlist",
  "request_id": "req-002"
}
```

**Example logs (Web):**
```json
{
  "request_id": "req-003",
  "path": "/web-read",
  "status": 403,
  "latency_ms": 5
}
{
  "level": "WARNING",
  "message": "Access denied: URL blocked",
  "request_id": "req-003"
}
```

**Operator actions:**
1. **Notion:** Add page ID to `NOTION_ALLOWED_PAGE_IDS` (comma-separated JSON array)
2. **Web:** Remove domain from `WEBREAD_BLOCKED_DOMAINS`
3. Restart application or wait for config reload (if hot-reload enabled)
4. Retry request

---

### 422 Unprocessable Entity — Validation Error

**Decision tree:**
```
Is parameter provided?
├─ No → Return 422 "field required"
└─ Yes
    └─ Is parameter value non-empty?
       ├─ No (empty string) → Return 422 "string must have length >= 1"
       └─ Yes → (Should not reach 422)
```

**Example logs:**
```json
{
  "request_id": "req-004",
  "path": "/web-read",
  "status": 422,
  "latency_ms": 2
}
{
  "detail": [
    {
      "loc": ["query", "url"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Operator actions:**
1. Check request URL for missing or empty parameter
2. Provide required parameter with valid value
3. Retry request

**Example corrections:**
```bash
# Wrong (missing)
curl "http://localhost:8000/web-read"

# Correct
curl "http://localhost:8000/web-read?url=https://example.com"

# Wrong (empty)
curl "http://localhost:8000/web-read?url="

# Correct
curl "http://localhost:8000/web-read?url=https://example.com"
```

---

### 502 Bad Gateway — Upstream Service Error

**Decision tree:**
```
Is upstream service reachable?
├─ No (network error) → Return 502 "Service error"
└─ Yes
    └─ Did upstream respond in time?
       ├─ No (fetch timeout) → Return 502 "Service timeout"
       └─ Yes
           └─ Is response valid?
              ├─ No (parse error) → Return 502 "Invalid response"
              └─ Yes → (Should not reach 502)
```

**Example logs (Web):**
```json
{
  "request_id": "req-005",
  "path": "/web-read",
  "status": 502,
  "latency_ms": 10001
}
{
  "level": "ERROR",
  "message": "Failed to fetch URL",
  "error": "ConnectionTimeout",
  "request_id": "req-005"
}
```

**Example logs (Notion/MCP):**
```json
{
  "request_id": "req-006",
  "path": "/notion-read/page",
  "status": 502,
  "latency_ms": 500
}
{
  "level": "ERROR",
  "message": "MCP protocol error",
  "error_type": "NotionAPIError",
  "request_id": "req-006"
}
```

**Operator actions:**
1. **Web Read:**
   - Verify target URL is reachable: `curl -I https://target.com`
   - Check network connectivity: `ping target.com`
   - Increase timeout if target is slow: `WEBREAD_TIMEOUT_SECONDS=20`
   - Restart application
   - Retry request

2. **Notion Read:**
   - Verify MCP server is running: `ps aux | grep notion-mcp-read`
   - Check Notion API token/credentials are valid
   - Check application logs for MCP error detail
   - Restart application
   - Retry request

---

### 503 Service Unavailable — Subprocess Not Ready

**Decision tree:**
```
Is MCP subprocess running?
├─ No → Return 503 "Service unavailable"
└─ Yes → (Should not reach 503)
```

**Note:** This is a Notion Read only error (graceful degradation).

**Example logs:**
```json
{
  "request_id": "req-007",
  "path": "/notion-read/page",
  "status": 503,
  "latency_ms": 8
}
{
  "level": "ERROR",
  "message": "Notion Read service unavailable",
  "request_id": "req-007"
}
```

**Operator actions:**
1. Check if MCP subprocess is running:
   ```bash
   ps aux | grep notion-mcp-read
   ```
2. If not running, restart application:
   ```bash
   docker compose restart api
   ```
3. Verify all environment variables are set:
   - `NOTION_MCP_SERVER_COMMAND`
   - `NOTION_MCP_SERVER_ARGS`
   - `NOTION_MCP_SERVER_CWD`
   - `NOTION_ROOT_PAGE_ID`
4. Check application startup logs for subprocess errors
5. Retry request

---

### 504 Gateway Timeout — Upstream Slow Response

**Decision tree:**
```
Is request taking too long?
├─ Yes (latency > timeout) → Return 504 "Timeout"
└─ No → (Should not reach 504)
```

**Note:** This is a Notion Read only error (Web Read returns 502 on timeout).

**Example logs:**
```json
{
  "request_id": "req-008",
  "path": "/notion-read/page",
  "status": 504,
  "latency_ms": 10001
}
{
  "level": "WARNING",
  "message": "MCP timeout",
  "timeout_seconds": 10,
  "request_id": "req-008"
}
```

**Operator actions:**
1. Check Notion API status (is it slow?)
2. Increase timeout if appropriate:
   ```bash
   NOTION_MCP_TIMEOUT_SECONDS=20
   ```
3. Restart application
4. Retry request
5. If persistent, check Notion API status page

---

### 500 Internal Server Error — Unexpected Error

**Decision tree:**
```
Is there an unhandled exception?
├─ Yes → Return 500 "Internal error"
└─ No → (Should not reach 500)
```

**Example logs:**
```json
{
  "request_id": "req-009",
  "path": "/web-read",
  "status": 500,
  "latency_ms": 45
}
{
  "level": "ERROR",
  "message": "Unexpected error in /web-read",
  "traceback": "Traceback (most recent call last): ...",
  "request_id": "req-009"
}
```

**Operator actions:**
1. Check application logs for traceback
2. Identify the root cause from the traceback
3. Restart application
4. Retry request
5. If persistent, contact support with:
   - Full traceback from logs
   - Request URL/parameters (redacted)
   - Environment variables (redacted)
   - Timestamp

---

## Status Code Distribution

### Success Path
- **200** — Request succeeds, upstream responds, data returned

### Client Error Path (4xx)
- **422** — Validation error (bad request parameters)
- **403** — Authorization error (blocked/disallowed resource)

### Server Error Path (5xx)
- **502** — Upstream service failure (fetch, API, protocol)
- **503** — Service degradation (subprocess unavailable)
- **504** — Upstream timeout (slow response)
- **500** — Unexpected server error (unhandled exception)

---

## Logging Correlation

All requests include `request_id` for end-to-end tracing:

```bash
# Get all logs for a failed request
docker logs llm-chat-platform-api | grep "req-001"

# Expected output:
# HTTP request log
# One or more error/warning logs
# Provider-specific logs (if applicable)
```

---

## Operator Runbook

### When you see HTTP 403:
1. Check allowlist/blocklist configuration
2. Confirm resource is supposed to be allowed
3. Update configuration if needed
4. Restart application

### When you see HTTP 422:
1. Check request URL for missing or empty parameters
2. Correct the request
3. Retry

### When you see HTTP 502:
1. Check upstream service reachability
2. Check upstream logs for errors
3. Increase timeout if applicable
4. Restart application

### When you see HTTP 503:
1. Check if subprocess is running
2. Restart application
3. Verify environment variables

### When you see HTTP 504:
1. Check upstream status
2. Increase timeout if appropriate
3. Restart application
4. Check Notion API status page

### When you see HTTP 500:
1. Check application logs for traceback
2. Identify root cause
3. Restart application
4. Contact support if persistent
