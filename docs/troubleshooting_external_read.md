# Troubleshooting External Read Capabilities

## Common Error Scenarios

### 1. 403 Forbidden — Access Denied

**Web Read:** URL in blocked domains list  
**Notion Read:** Page ID not in allowlist

#### Error Message
```
HTTP 403 Forbidden
{"detail": "Access denied: page not in allowlist"}  # Notion
{"detail": "Access denied: URL blocked"}            # Web (if applicable)
```

#### Diagnosis

**Web Read:**
```bash
# Check blocked domains config
grep WEBREAD_BLOCKED_DOMAINS .env

# Test with a different domain
curl "http://localhost:8000/web-read?url=https://example.com"
```

**Notion Read:**
```bash
# Check allowlist
grep NOTION_ALLOWED_PAGE_IDS .env

# Verify page ID format (UUID)
# Example: 12345678-1234-5678-1234-567812345678
```

#### Resolution

**Web Read:**
- If the domain should be allowed, remove it from `WEBREAD_BLOCKED_DOMAINS`
- Restart the application
- Retest the request

**Notion Read:**
1. Get the page ID from Notion page URL
2. Extract the ID after the last `-` in the URL
3. Add to `NOTION_ALLOWED_PAGE_IDS` array in `.env`:
   ```bash
   NOTION_ALLOWED_PAGE_IDS=["existing-id", "new-id"]
   ```
4. Restart the application
5. Retest the request

#### Example Logs
```json
{"request_id": "req-123", "path": "/notion-read/page", "status": 403, "latency_ms": 12}
{"level": "WARNING", "message": "Page blocked by allowlist", "page_id": "redacted"}
```

---

### 2. 502 Bad Gateway — Upstream Service Error

**Web Read:** Network error, timeout, invalid HTML, or fetch failure  
**Notion Read:** Notion API error or MCP protocol error

#### Error Message
```
HTTP 502 Bad Gateway
{"detail": "Notion Read service error"}       # Notion
{"detail": "Failed to fetch URL"}             # Web
```

#### Diagnosis

**Web Read:**
```bash
# Test connectivity to the target URL
curl -I https://example.com

# Check for network issues
ping example.com

# Verify timeout setting
grep WEBREAD_TIMEOUT_SECONDS .env
```

**Notion Read:**
```bash
# Check if MCP server is running
ps aux | grep notion-mcp-read

# Verify server command and args in .env
grep NOTION_MCP_SERVER_COMMAND .env
grep NOTION_MCP_SERVER_ARGS .env

# If running in Docker, confirm Node.js exists inside the API image
docker compose exec api node --version

# If running in Docker, confirm the mounted server path exists
docker compose exec api ls -la /notion-mcp-server/dist/server.js

# Test Notion API connectivity (requires auth token)
curl -H "Authorization: Bearer <NOTION_TOKEN>" \
  https://api.notion.com/v1/pages/<page-id>
```

#### Resolution

**Web Read:**
1. Check if the target URL is reachable and responsive
2. Increase timeout if needed:
   ```bash
   WEBREAD_TIMEOUT_SECONDS=20
   ```
3. Check application logs for fetch error details
4. Restart and retest

**Notion Read:**
1. Verify MCP server is running:
   ```bash
   node /path/to/notion-mcp-read/dist/server.js
   ```
2. If the API runs in Docker, ensure the image includes Node.js and the server is mounted at `/notion-mcp-server`
3. Check environment variables are set correctly:
   - `NOTION_MCP_SERVER_COMMAND`
   - `NOTION_MCP_SERVER_ARGS`
   - `NOTION_MCP_SERVER_CWD`
   - `NOTION_ROOT_PAGE_ID`
4. Check Notion API token/credentials are valid
5. Restart the application

#### Example Logs
```json
{"request_id": "req-124", "path": "/web-read", "status": 502, "latency_ms": 15000}
{"level": "ERROR", "message": "MCP protocol error", "error_type": "timeout"}
```

---

### 3. 504 Gateway Timeout — Slow Upstream Response

**Notion Read only** (Web Read returns 502 on timeout)

#### Error Message
```
HTTP 504 Gateway Timeout
{"detail": "Notion Read service timeout"}
```

#### Diagnosis

**Notion Read:**
```bash
# Check current timeout setting
grep NOTION_MCP_TIMEOUT_SECONDS .env

# Check Notion API response time
time curl -H "Authorization: Bearer <TOKEN>" \
  https://api.notion.com/v1/pages/<page-id>
```

#### Resolution

1. Increase MCP timeout if appropriate:
   ```bash
   NOTION_MCP_TIMEOUT_SECONDS=20  # Increase from 10 to 20
   ```
2. Check if Notion API is experiencing degradation
3. Reduce request volume or add client-side retry logic
4. Restart and retest

#### Example Logs
```json
{"request_id": "req-125", "path": "/notion-read/page", "status": 504, "latency_ms": 10000}
{"level": "WARNING", "message": "MCP timeout", "timeout_seconds": 10}
```

---

### 4. 503 Service Unavailable — MCP Subprocess Not Available

**Notion Read only** (graceful degradation)

#### Error Message
```
HTTP 503 Service Unavailable
{"detail": "Notion Read service unavailable"}
```

#### Diagnosis

**Notion Read:**
```bash
# Check if MCP subprocess is running
ps aux | grep notion-mcp-read

# Check for subprocess errors in application logs
docker logs llm-chat-platform-api

# Verify server working directory exists
ls -la $(grep NOTION_MCP_SERVER_CWD .env | cut -d= -f2)
```

#### Resolution

1. Restart the application (MCP server should be auto-spawned):
   ```bash
   docker compose restart api
   ```
2. Check application startup logs for MCP initialization errors
3. Verify all required environment variables are set
4. Verify the notion-mcp-read server binary exists and is executable
5. Check system resource limits (memory, file descriptors)

#### Example Logs
```json
{"request_id": "req-126", "path": "/notion-read/page", "status": 503, "latency_ms": 8}
{"level": "ERROR", "message": "Notion Read service unavailable"}
```

---

### 5. 422 Unprocessable Entity — Validation Error

**Both endpoints:** Missing or invalid required parameter

#### Error Message
```
HTTP 422 Unprocessable Entity
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

#### Diagnosis

**Web Read:**
```bash
# Missing parameter
curl "http://localhost:8000/web-read"

# Invalid parameter (empty string)
curl "http://localhost:8000/web-read?url="
```

**Notion Read:**
```bash
# Missing parameter
curl "http://localhost:8000/notion-read/page"

# Invalid parameter (empty string)
curl "http://localhost:8000/notion-read/page?page_id="
```

#### Resolution

Provide the required parameter with a valid value:

**Web Read:**
```bash
curl "http://localhost:8000/web-read?url=https://example.com"
```

**Notion Read:**
```bash
curl "http://localhost:8000/notion-read/page?page_id=12345678-1234-5678-1234-567812345678"
```

---

## Configuration Checklist

### Web Read Verification

```bash
# ✅ Required environment variables set?
echo "WEBREAD_BLOCKED_DOMAINS: $(printenv WEBREAD_BLOCKED_DOMAINS)"
echo "WEBREAD_TIMEOUT_SECONDS: $(printenv WEBREAD_TIMEOUT_SECONDS)"
echo "WEBREAD_MAX_CONTENT_LENGTH: $(printenv WEBREAD_MAX_CONTENT_LENGTH)"

# ✅ Endpoint reachable?
curl -I "http://localhost:8000/web-read?url=https://example.com"

# ✅ Application logs show no errors?
docker logs llm-chat-platform-api | grep -i "web"
```

### Notion Read Verification

```bash
# ✅ Required environment variables set?
echo "NOTION_ROOT_PAGE_ID: $(printenv NOTION_ROOT_PAGE_ID | cut -c1-8)..."
echo "NOTION_ALLOWED_PAGE_IDS: $(printenv NOTION_ALLOWED_PAGE_IDS)"
echo "NOTION_MCP_SERVER_COMMAND: $(printenv NOTION_MCP_SERVER_COMMAND)"
echo "NOTION_MCP_SERVER_CWD: $(printenv NOTION_MCP_SERVER_CWD)"

# ✅ MCP server running?
ps aux | grep notion-mcp-read

# ✅ Endpoint reachable?
curl -I "http://localhost:8000/notion-read/page?page_id=test"

# ✅ Application logs show no errors?
docker logs llm-chat-platform-api | grep -i "notion"
```

---

## Structured Logging Examples

### Successful Request

```json
{
  "request_id": "req-001",
  "path": "/web-read",
  "method": "GET",
  "status": 200,
  "latency_ms": 234,
  "app_env": "development"
}
```

### Blocked Request (403)

```json
{
  "request_id": "req-002",
  "path": "/notion-read/page",
  "method": "GET",
  "status": 403,
  "latency_ms": 12,
  "app_env": "development"
}

{
  "level": "WARNING",
  "message": "Page blocked by allowlist",
  "request_id": "req-002"
}
```

### Timeout Request (504)

```json
{
  "request_id": "req-003",
  "path": "/notion-read/page",
  "method": "GET",
  "status": 504,
  "latency_ms": 10001,
  "app_env": "development"
}

{
  "level": "WARNING",
  "message": "MCP timeout",
  "request_id": "req-003",
  "timeout_seconds": 10
}
```

---

## Health Check Script

To verify both endpoints are operational:

```bash
#!/bin/bash
set -e

API_BASE="http://localhost:8000"

echo "Checking Web Read endpoint..."
curl -s -f "$API_BASE/web-read?url=https://example.com" > /dev/null
echo "✓ Web Read OK"

echo "Checking Notion Read endpoint..."
curl -s -f "$API_BASE/notion-read/page?page_id=test-id" 2>/dev/null || echo "⚠ Notion Read requires valid page_id in allowlist"
echo "✓ Notion Read endpoint reachable"

echo "All checks passed!"
```

Save as `verify_read_endpoints.sh` and run:
```bash
chmod +x verify_read_endpoints.sh
./verify_read_endpoints.sh
```

---

## When to Escalate

Contact support if:

1. **Multiple 502 errors** after configuration is correct
2. **503 error persists** after application restart
3. **504 timeouts** are frequent (indicating upstream degradation)
4. **403 errors** for page IDs that should be allowed
5. **500 errors** (unexpected server errors)

Provide:
- Full error message and status code
- Request URL/parameters (redacted if sensitive)
- Relevant environment variables (redacted)
- Application logs (last 50 lines)
- Timestamp of occurrence
