# Pre-ORQ-19 Multitenancy Revalidation

Date: 2026-07-02  
Branch: `main`  
Validated HEAD: `c548ecfcceaa2d14bfa6fa01998578e784dab8a1`

## Global verdict

**NO-GO for ORQ-19.**

The live multitenancy checks passed, and the three required GitHub workflows are
green at the validated HEAD. However, the required complete local pytest run
did not finish. It hangs reproducibly in the first test and therefore cannot be
reported as green.

No application code, migrations, provider contracts, persistence flow, or
streaming behavior was modified during this validation.

## Repository and environment preparation

```console
$ git pull --ff-only
Already up to date.

$ git rev-parse HEAD
c548ecfcceaa2d14bfa6fa01998578e784dab8a1

$ git merge-base --is-ancestor v1.1-stable HEAD
# exit 0
```

`v1.1-stable` is present in the history of the validated HEAD.

The API image was rebuilt before startup:

```console
$ docker compose build api
Image llm-chat-platform-api Built

$ docker compose up -d
Container llm-chat-redis Running
Container llm-chat-postgres Running
Container llm-chat-api Started
```

The Alembic configuration is stored under `app/`, so the explicit migration
commands used inside the rebuilt container were:

```console
$ docker compose exec -T api alembic -c app/alembic.ini upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.

$ docker compose exec -T api alembic -c app/alembic.ini current
a1b2c3d4e5f6 (head)
```

## Contracts derived from code

The request shape was derived from `app/schemas/chat.py` and
`app/api/routes/chat.py`, not assumed:

```json
{
  "message": "non-blank string",
  "conversation_id": "optional UUID",
  "stream": false
}
```

`POST /chat` returns a JSON `ChatResponse` when `stream=false` and SSE
`token`, `done`, or `error` events when `stream=true`.

`GET /conversations` accepts optional integer query parameters `limit`
(default 20, clamped to 1..100) and `offset` (default 0, clamped to at least
zero). Its response contains `items`, `limit`, and `offset`.

## Automated validation

### Complete local pytest

Result: **FAIL (hang / timeout; no assertion failure observed).**

The full run collected 249 tests but stopped making progress at the first test:

```console
$ python -m pytest -ra
collected 249 items

tests/api/test_chat_guardrails.py
```

Disabling the optional Notion integration for the test process did not remove
the hang. The minimal reproduction is:

```console
$ timeout 20s env NOTION_MCP_ENABLED=false NOTION_READ_ENABLED=false \
    python -m pytest -vv -s \
    tests/api/test_chat_guardrails.py::test_chat_rejects_blank_message
collected 1 item

tests/api/test_chat_guardrails.py::test_chat_rejects_blank_message
2026-07-02T10:18:20-0300 INFO app app starting application tenant_id=default
# process timed out; exit 124
```

Preliminary cause: the local ASGI test request blocks after lifespan startup
and before the blank-message response. The hang remains when Notion MCP is
disabled, so Notion is not the direct cause. The exact deadlock point requires
separate diagnosis; no code was changed as part of this validation task.

### GitHub Actions at validated HEAD

All three latest runs on `main` for `c548ecf` completed successfully:

| Workflow | Result | Run |
|---|---:|---|
| CI | PASS | `28589836828` |
| Governance Reconciliation | PASS | `28589837003` |
| Guardrails | PASS | `28589837067` |

Operational caveat: the CI workflow runs a narrowed pytest baseline, not the
complete 249-test local suite.

## Live API validation

One real-provider smoke request was executed with Bedrock. The API was then
recreated with `PRIMARY_PROVIDER=stub` through a temporary Compose override in
`/tmp`; no repository configuration was changed.

| Test | Result | Evidence summary |
|---|---:|---|
| 1a — write isolation | PASS | Bedrock request as `tenant-a` returned 200 and conversation `9ca7e174-8c02-4299-9784-3078a01cec89`. |
| 1b — cross-tenant continuation | PASS | Continuing that ID as `tenant-b` returned 404. |
| 2 — default fallback | PASS | Headerless request returned 200; Postgres stored tenant `default`. |
| 3 — namespaced cache | PASS | Redis contained separate `tenant-a` and `default` keys with the same digest; same-tenant retry logged a hit. |
| 4 — ORQ-18.2 read regression | PASS | Each response exactly matched the IDs assigned to its tenant in Postgres. |
| 5 — tenant plus SSE | PASS | Complete stream ended with `done`; final Postgres row retained `tenant-a`. |
| 6 — middleware order | PASS | Runtime order starts with `TenantMiddleware`, confirming it is outermost. |

### Test 1a — write isolation

```console
$ curl -sS -i --max-time 45 -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    -H 'X-Tenant-ID: tenant-a' \
    --data '{"message":"ORQ-19 prevalidation tenant isolation smoke 2026-07-02","stream":false}'
HTTP/1.1 200 OK
...
{"conversation_id":"9ca7e174-8c02-4299-9784-3078a01cec89",...,"status":"success","error_message":null}
```

This was the single real-provider Bedrock smoke request.

### Test 1b — cross-tenant continuation

```console
$ curl -sS -i --max-time 15 -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    -H 'X-Tenant-ID: tenant-b' \
    --data '{"conversation_id":"9ca7e174-8c02-4299-9784-3078a01cec89","message":"Cross-tenant continuation must fail","stream":false}'
HTTP/1.1 404 Not Found
...
{"detail":"conversation_id not found"}
```

### Test 2 — default tenant fallback

```console
$ curl -sS -i --max-time 20 -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    --data '{"message":"ORQ-19 default tenant fallback validation 2026-07-02","stream":false}'
HTTP/1.1 200 OK
...
{"conversation_id":"b7da5c94-e9d8-4cce-a90c-29f1536fc0ba",...,"status":"success"}

$ docker compose exec -T postgres sh -lc \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -x \
    -c "SELECT id, tenant_id FROM conversations WHERE id = '\''b7da5c94-e9d8-4cce-a90c-29f1536fc0ba'\'';"'
id        | b7da5c94-e9d8-4cce-a90c-29f1536fc0ba
tenant_id | default
```

### Test 3 — namespaced response cache

The same prompt was sent first as `tenant-a`, then without a tenant header, and
then again as `tenant-a`:

```console
$ curl -sS -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    -H 'X-Tenant-ID: tenant-a' \
    --data '{"message":"ORQ19 cache namespace proof 2026-07-02T13:12Z","stream":false}'
{"conversation_id":"d3b642ff-8b94-406b-9461-8d0b7c79e6a0",...,"status":"success"}

$ curl -sS -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    --data '{"message":"ORQ19 cache namespace proof 2026-07-02T13:12Z","stream":false}'
{"conversation_id":"d2c4f0de-efb2-4be0-8258-0868cb984e78",...,"status":"success"}

$ curl -sS -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    -H 'X-Tenant-ID: tenant-a' \
    --data '{"message":"ORQ19 cache namespace proof 2026-07-02T13:12Z","stream":false}'
{"conversation_id":"c1468414-c79b-42f2-b795-de867286e816",...,"status":"success"}
```

```console
$ docker compose exec -T redis redis-cli KEYS 'chat:response:*'
chat:response:default:7d98172b69349e5344f7e25cdc25fea0394ba64411ac7a1b931e7414e0717904
chat:response:tenant-a:7d98172b69349e5344f7e25cdc25fea0394ba64411ac7a1b931e7414e0717904

$ docker compose logs --no-color --since 5m api | \
    rg 'chat_cache_(miss|hit)|chat\.cache\.(miss|hit)'
chat_cache_miss tenant_id=tenant-a
chat_cache_miss tenant_id=default
chat_cache_hit tenant_id=tenant-a
```

### Test 4 — ORQ-18.2 read isolation regression

```console
$ curl -sS -i 'http://localhost:8001/conversations?limit=100&offset=0' \
    -H 'X-Tenant-ID: tenant-a'
HTTP/1.1 200 OK
{"items":[
  {"conversation_id":"c1468414-c79b-42f2-b795-de867286e816",...},
  {"conversation_id":"d3b642ff-8b94-406b-9461-8d0b7c79e6a0",...},
  {"conversation_id":"9ca7e174-8c02-4299-9784-3078a01cec89",...},
  {"conversation_id":"3a4dbf23-beb6-45fa-9c5e-4ecbca575d62",...}
],"limit":100,"offset":0}

$ curl -sS -i 'http://localhost:8001/conversations?limit=100&offset=0' \
    -H 'X-Tenant-ID: tenant-b'
HTTP/1.1 200 OK
{"items":[],"limit":100,"offset":0}

$ curl -sS -i 'http://localhost:8001/conversations?limit=100&offset=0'
HTTP/1.1 200 OK
{"items":[
  {"conversation_id":"d2c4f0de-efb2-4be0-8258-0868cb984e78",...},
  {"conversation_id":"b7da5c94-e9d8-4cce-a90c-29f1536fc0ba",...},
  {"conversation_id":"60e00ec3-a3d9-467b-8365-5338fdd6b404",...},
  {"conversation_id":"fe4295ba-12d9-43aa-ac10-9a61712f63ba",...},
  {"conversation_id":"11a57a79-9c16-48ac-b7e5-1420aeee7ef8",...}
],"limit":100,"offset":0}
```

The Postgres ground truth contained exactly those IDs grouped under
`tenant-a` and `default`; it contained no `tenant-b` conversations.

### Test 5 — tenant context through complete SSE stream

```console
$ curl -sS -N --max-time 20 -i -X POST http://localhost:8001/chat \
    -H 'Content-Type: application/json' \
    -H 'Accept: text/event-stream' \
    -H 'X-Tenant-ID: tenant-a' \
    --data '{"message":"ORQ-19 streaming ContextVar persistence validation 2026-07-02","stream":true}'
HTTP/1.1 200 OK
content-type: text/event-stream; charset=utf-8
...
event: done
data: {"request_id":"0381e5b5-3645-4ab2-9ba9-dfca82579b69","conversation_id":"3e5f40ad-167f-428f-852a-f652cde2d076",...,"status":"success"}

$ docker compose exec -T postgres sh -lc \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -x \
    -c "SELECT id, tenant_id FROM conversations WHERE id = '\''3e5f40ad-167f-428f-852a-f652cde2d076'\'';"'
id        | 3e5f40ad-167f-428f-852a-f652cde2d076
tenant_id | tenant-a
```

### Test 6 — middleware ordering

Source registration order:

```python
app.add_middleware(RequestContextMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(StructuredJsonLoggingMiddleware, app_env=...)
app.add_middleware(TenantMiddleware)
```

Effective runtime order:

```console
$ docker compose exec -T api python -c \
    'from app.main import app; print([m.cls.__name__ for m in app.user_middleware])'
['TenantMiddleware', 'StructuredJsonLoggingMiddleware', 'RequestSizeLimitMiddleware', 'RequestContextMiddleware']
```

Starlette applies user middleware in LIFO registration order.
`TenantMiddleware` remains the outermost middleware. This is the current order
to preserve or deliberately account for in ORQ-19.6 CORS work.

## Corrective follow-up required before GO

Create a separate ORQ to diagnose the local ASGI pytest hang and obtain a
successful complete `python -m pytest` run. The investigation should begin at
the global `client` fixture request path and the middleware stack, using the
minimal reproduction above. Do not infer success from the current CI workflow,
because it runs only a narrowed subset.
