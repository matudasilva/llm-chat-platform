# LLD Appendix — LLM Chat Platform

**Companion document to:** `lld_llm_chat_platform_live_doc.md`

**Scope:** Deep technical appendices, debugging playbooks, and execution-level details

**Validity:** Up to Day 16 (Appendix L)


> Note:
> Appendices A–E describe the effective system state up to Day 9.
> Appendix F documents the Day 10 traceability layer (read-only reconstruction).
> Later appendices record incremental architectural and operational changes through Day 16.



---

## Appendix A — SQL schema & constraints (expected state)

> This section documents the **effective schema semantics** as enforced by Alembic migrations and runtime behavior.

### A.1 `conversations`

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  title TEXT NULL,
  metadata JSONB NULL
);
```

**Semantics**

* Acts as aggregation root for messages
* Created lazily on first `/chat` request
* No hard deletes assumed

---

### A.2 `messages`

```sql
CREATE TABLE messages (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation_created
  ON messages(conversation_id, created_at);
```

**Semantics**

* Ordering guaranteed by `(conversation_id, created_at)`
* FK enforces existence of conversation
* `system` role reserved for orchestration

---

### A.3 `usage_events`

```sql
CREATE TABLE usage_events (
  id UUID PRIMARY KEY,
  provider TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  request_id UUID NULL,
  conversation_id UUID NULL REFERENCES conversations(id),
  message_id UUID NULL REFERENCES messages(id),
  input_tokens INTEGER NULL,
  output_tokens INTEGER NULL,
  total_tokens INTEGER NULL,
  latency_ms INTEGER NULL,
  status TEXT NOT NULL,
  error_message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_usage_events_request_id ON usage_events(request_id);
CREATE INDEX idx_usage_events_conversation_ts ON usage_events(conversation_id, created_at);
CREATE INDEX idx_usage_events_message_id ON usage_events(message_id);
```

**Critical design note**

* `conversation_id` and `message_id` are **nullable by design**
* Error telemetry must never depend on business data success

---

## Appendix B — `/chat` sequence diagram (textual)

### B.1 Happy path

```
Client
  └─ POST /chat
       └─ generate request_id
       └─ start timer
       └─ BEGIN TRANSACTION
            └─ create Conversation (if needed)
            └─ flush → conversation_id
            └─ insert Message(role=user)
            └─ flush → user_message_id
            └─ execute model (stub)
            └─ insert Message(role=assistant)
            └─ flush → assistant_message_id
            └─ insert UsageEvent (with FKs)
       └─ COMMIT
       └─ return ChatResponse
```

**Guarantees**

* Atomic write-path
* No partial persistence
* Telemetry consistent with business data

---

### B.2 Error path (unexpected failure)

```
Client
  └─ POST /chat
       └─ generate request_id
       └─ BEGIN TRANSACTION
            └─ failure occurs
       └─ ROLLBACK
       └─ BEGIN (best-effort)
            └─ insert UsageEvent(status=error, no FKs)
       └─ COMMIT
       └─ re-raise exception
```

**Guarantees**

* Database consistency preserved
* Error observability retained

---

## Appendix C — Router & import map

### C.1 Canonical router layout

```
app/main.py
  ├─ include_router(ops_router, prefix="/ops")
  └─ include_router(chat_router, prefix="/chat")

app/api/routes/chat.py
  └─ router = APIRouter(tags=["chat"])
```

**Invariant**

* Only one authoritative chat router
* No shadow routers or duplicate includes

---

### C.2 Known anti-patterns (resolved)

* Importing non-existent `app.api.chat`
* Multiple routers defining `/chat`
* Dynamic router discovery

---

## Appendix D — Debug playbook

### D.1 `/chat` missing from OpenAPI

**Symptoms**

* `/chat` not present in `/openapi.json`

**Checks**

```bash
curl -s http://localhost:8001/openapi.json | jq '.paths | keys'
```

**Likely causes**

* Router not included in `main.py`
* Import-time crash in container

---

### D.2 Container exits immediately

**Symptoms**

* `docker compose ps` shows API exited

**Checks**

```bash
docker compose logs api
```

**Common causes**

* Indentation errors
* Invalid imports
* Missing dependencies

---

### D.3 FK violation on `usage_events`

**Symptoms**

```
ForeignKeyViolationError: Key (conversation_id) not present
```

**Cause**

* Logging usage events with FKs after rollback

**Resolution**

* Success telemetry inside transaction
* Error telemetry without FKs

---

### D.4 Verifying DB state

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select role, count(*) from messages group by role;"
```

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select provider, status, conversation_id, message_id from usage_events order by created_at desc limit 5;"
```
### D.5 RequestSizeLimitMiddleware raises `KeyError: 'receive'` under TestClient

**Symptoms**

Pytest fails on requests (typically `POST /chat`) with:

KeyError: 'receive'


originating from:

- `app/http/middleware/request_size_limit.py`

**Cause**

`BaseHTTPMiddleware` in Starlette wraps requests in a way that can make `request.scope["receive"]`
unavailable or unsafe to mutate, depending on the execution path.

**Resolution (validated)**

Use an ASGI middleware (pure `__call__(scope, receive, send)`) or guard for missing `receive`
and fall back to `call_next(request)`.

**Regression test evidence**

- `tests/api/test_chat_guardrails.py` executes via `TestClient` and must pass.
- Passing suite confirms middleware compatibility with Starlette test transport.

### D.6 `ChatService.__init__()` mismatch: missing `timeout_s`

**Symptoms**

Pytest collection/execution fails with:

TypeError: ChatService.init() missing 1 required keyword-only argument: 'timeout_s'


Trigger points observed:

- core contract tests instantiating `ChatService(provider)`
- FastAPI dependency `get_chat_service()` instantiating `ChatService(provider=get_provider())`

**Cause**

`ChatService` constructor changed to require `timeout_s` (keyword-only), but call sites were not updated.

**Resolution (validated)**

- Update all call sites to pass `timeout_s=...`
- Update contract tests accordingly
- Wire a single settings-backed value via DI layer (`app/api/deps.py`)

**Regression evidence**

- `app/tests/core/test_chat_service_contract.py`
- API tests (which hit DI): `tests/api/test_chat_guardrails.py`

---

## Appendix E — Operational sanity checklist

* [ ] Alembic current == heads
* [ ] API container running
* [ ] `/health` responds
* [ ] `/chat` persists messages
* [ ] `usage_events` populated

---

## Appendix F — End-to-End Traceability (Day 10)

### F.1 Purpose

This appendix documents the internal mechanics and validation rules used to achieve **end-to-end traceability** of a single `/chat` execution, reconstructed from a `request_id`.

The objective is to provide **auditable, implementation-level detail** without introducing changes to the primary write-path, schema, or public API surface.

---

### F.2 Traceability Scope

The traceability mechanism is intentionally designed as **read-only and non-invasive**:

* No changes to the `/chat` transactional flow
* No changes to Alembic migrations
* No schema recreation or backfills
* No additional public API endpoints

All reconstruction is performed via **internal services and offline scripts**, operating exclusively on persisted data.

---

### F.3 Reconstruction Flow (D1)

Given a `request_id`:

1. Retrieve all `UsageEvent` records matching the request
2. Select a `primary_event`

   * Prefer `status = success`
   * Fallback to the most recent event otherwise
3. Resolve `conversation_id` from the primary event
4. Load the associated `Conversation`
5. Load all `Message` records for the conversation

   * Ordered deterministically by `(created_at, id)`
6. Reconstruct the input/output pair:

   * `output_message` resolved directly from `UsageEvent.message_id`
   * `input_message` resolved as the nearest preceding `user` message

---

### F.4 Edge Case Handling

#### Identical Timestamps

In scenarios where `user` and `assistant` messages share identical timestamps:

* Temporal comparison alone is insufficient
* Positional ordering within the deterministic message list is used
* Backward traversal ensures correct `user → assistant` pairing

This guarantees correctness under high-throughput or low-latency conditions.

---

### F.5 Enum Normalization

Both `Message.role` and `UsageEvent.status` may be represented as enums or strings depending on execution context.

A normalization step is applied:

* Enum values resolved via `.value` when present
* Fully-qualified enum strings reduced to terminal values
* All comparisons performed against lowercase canonical forms

This prevents false negatives during reconstruction and coherence checks.

---

### F.6 Coherence Checks

Each trace reconstruction produces an explicit **coherence report**.

**Checks performed**

* `usage_event_found`
* `single_usage_event`
* `success_has_fks`
* `conversation_found`
* `messages_loaded`
* `input_output_resolved`

Each check records:

* `name`
* Boolean result (`ok`)
* Optional diagnostic detail

---

### F.7 Errors vs Warnings

* **Errors** indicate invariant violations and cause trace failure
* **Warnings** indicate best-effort limitations but allow trace completion

---

### F.8 Example Output (Redacted)

```json
{
  "request_id": "<uuid>",
  "reconstruction": {
    "input_message": { "role": "user", "content": "..." },
    "output_message": { "role": "assistant", "content": "..." }
  },
  "coherence": {
    "errors": [],
    "warnings": [],
    "checks": [
      { "name": "input_output_resolved", "ok": true }
    ]
  }
}
```

---

### F.9 Design Rationale

This traceability design intentionally prioritizes:

* Determinism over heuristics
* Explicit checks over implicit assumptions
* Read-path analysis over write-path modification

The result is a trace system that is **auditable, debuggable, and safe for production environments**.



---

## Appendix G — Provider Abstraction & Determinism Evidence (Day 11)

### G.1 Purpose

This appendix documents the **provider abstraction layer** introduced in Day 11 and the deterministic validation artifacts associated with it.

Scope and constraints:

* No changes to the `/chat` transactional write-path
* No modifications to Alembic migrations
* No changes to persistence models

The objective is to validate provider contracts **before** integrating real LLM vendors, preserving architectural invariants established in previous days.

---

### G.2 Runtime import root (important)

Inside the `api` container, the effective application root is:

```
/app/app
```


As a result:

* Top-level imports are resolved from modules such as `core`, `api`, `models`, `infra`, and `services`
* There is **no synthetic `app.*` package** in runtime

This convention applies consistently to:

* Domain code
* Runners
* Tests

**Quick verification**

Inside container:

```bash
docker compose exec -T -w /app/app api python -c "import sys; print(sys.path); import core; print(core.__file__)"
```

Host execution (repo root):

```bash
PYTHONPATH=app python -c "import core; print(core.__file__)"
```

---

### G.3 Provider abstraction (Day 11)

A provider is modeled via an **async-first port**, fully decoupled from HTTP and persistence concerns.

Key characteristics:

* Providers implement a single operation:

  ```
  ProviderPort.generate(input: ProviderInput) -> ProviderResult
  ```

* `ProviderInput` is domain-only and includes:

  * `request_id`
  * a sequence of domain `ChatMessage`
  * optional runtime hints

* `ProviderResult` is also domain-only and includes:

  * generated `content`
  * required metadata (`provider`, `model_version`, `prompt_version`)
  * optional metrics (`input_tokens`, `output_tokens`, `total_tokens`, `latency_ms`)

Explicit non-goals:

* No database foreign keys in `ProviderResult`
* No `status` field (request outcome is a write-path concern)

This separation preserves **best-effort telemetry** guarantees under failure conditions.



---

### G.4 StubProvider (deterministic, no IO)

A deterministic `StubProvider` is implemented to validate the provider contract prior to real integrations.

Properties:

* Output is deterministically derived from `request_id` and input content
* Configurable simulated latency
* Configurable deterministic error mode
* No external IO
* No persistent side effects

This makes both success and failure paths **fully reproducible**.

---

### G.5 ChatService (DB-agnostic orchestration)

`ChatService` is introduced as a pure orchestration layer:

Responsibilities:

* Accept domain messages
* Invoke the injected provider
* Produce an assistant domain message and provider metadata

Non-responsibilities:

* No database access
* No transaction handling
* No HTTP or FastAPI semantics

The service returns a `ChatServiceResult` containing:

* `request_id`
* `assistant_message`
* `provider_result`

This result is intentionally shaped to be consumed later by the `/chat` write-path.

---

### G.6 Reproducible runners

The following runners provide executable evidence of correctness and determinism.

**Success and error paths**:

```bash
docker compose exec -T -w /app/app api sh -lc 'PYTHONPATH=/app/app python scripts/run_stub_chat.py'
```

**Determinism and sensitivity checks**:

```bash
docker compose exec -T -w /app/app api sh -lc 'PYTHONPATH=/app/app python scripts/run_stub_determinism.py'
```

---

### G.7 Contract tests (host execution)

Contract tests are intentionally pure and do not require database or container execution.

From the repository root:

```bash
pip install -r app/requirements-dev.txt
PYTHONPATH=app pytest
```

Test coverage includes:

* Provider determinism
* Provider error propagation
* Metric coherence
* ChatService behavior and error forwarding

---

### G.8 Design notes

* Provider contracts are validated **before** vendor integration
* Determinism is enforced to simplify debugging and traceability
* Observability concerns remain decoupled from business data persistence
* Integration with `/chat` is intentionally deferred to the next iteration

---

**End of Appendix G (Day 11)**

---

## Appendix H — Day 12: `/chat` integration evidence

### H.1 Purpose

This appendix documents the reproducible evidence for the Day 12 integration of
`ChatService` into the `/chat` write-path.

The goal of this iteration was **integration without feature expansion**:
- preserve atomicity of the write-path
- preserve flush ordering and foreign key integrity
- validate error propagation and rollback semantics
- provide concrete, repeatable evidence of correct behavior

No changes to the data model or migrations were introduced.

---

### H.2 Provider mode wiring (`STUB_PROVIDER_MODE`)

The active provider mode is controlled via the environment variable
`STUB_PROVIDER_MODE`, allowing deterministic success and failure scenarios.

This variable is injected into the `api` service via Docker Compose and is
consumed by the provider wiring layer when constructing the `StubProvider`.

**Valid values:**
- `ok` (default): provider returns a deterministic response
- `error`: provider raises an exception during generation

**Verification inside the running container:**

```bash
docker compose exec -T api sh -lc \
  'python -c "import os; print(os.getenv(\"STUB_PROVIDER_MODE\"))"'
```

This mechanism enables reproducible validation of both success and error paths
without modifying application code.

### H.3 Endpoint smoke runners (success and rollback)

Two smoke runners are provided to validate the `/chat` endpoint behavior
end-to-end, including persistence and telemetry.

#### H.3.1 Success path

Validates that:
- the user message and assistant message are persisted
- a `UsageEvent` with status `success` is emitted
- foreign keys (`conversation_id`, `message_id`) are present and valid

**Commands:**

```bash
STUB_PROVIDER_MODE=ok docker compose up -d --build

until curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/openapi.json | grep -q 200; do
  sleep 1
done

PYTHONPATH=app python app/scripts/run_chat_endpoint_smoke.py
```
Expected output includes:

```bash
[OK] success path validated
```




#### H.3.2 Error path (rollback validation)

Validates that:
- a provider failure triggers a full transactional rollback
- no new messages are persisted
- a `UsageEvent` with status `error` is emitted
- foreign keys are intentionally omitted (best-effort telemetry)

**Commands:**

```bash
STUB_PROVIDER_MODE=error docker compose up -d --build

until curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/openapi.json | grep -q 200; do
  sleep 1
done

STUB_PROVIDER_MODE=error PYTHONPATH=app \
  python app/scripts/run_chat_endpoint_error_smoke.py
```

Expected output includes:
```bash
[OK] error path validated (rollback + best-effort usage_event)
```
### H.4 Regression gates

The following regression checks must pass after Day 12 integration:

- **Core contract tests (DB-agnostic):**

```bash
  PYTHONPATH=app pytest -q
```
- **API surface stability:**
  - `/chat` remains the single write-path
  - read-path endpoints (`/conversations`, `/usage-events`) remain unchanged
  - OpenAPI schema is preserved

Successful execution of these checks confirms that the Day 12 integration
introduced no regressions and preserved all architectural invariants.

### H.5 Guardrails & provider-boundary regression gates (A2/A3)

The following checks validate that input guardrails and provider execution boundaries remain intact.

#### H.5.1 API guardrails (blank + oversized message)

Validates that `/chat` rejects invalid input deterministically:

- blank / whitespace-only message → request rejected
- message exceeding `settings.max_message_chars` → request rejected

**Command:**

```bash
PYTHONPATH=app pytest -q tests/api/test_chat_guardrails.py
```
Expected:

test suite passes

no DB writes are produced for rejected inputs

H.5.2 Provider error normalization (contract-level)

Validates that provider exceptions do not cross the ChatService boundary:

provider failure → ProviderExecutionError raised

original exception is preserved as __cause__ for debugging

Command:
```bash
PYTHONPATH=app pytest -q app/tests/core/test_chat_service_contract.py
```
Expected:

test suite passes

error type and message match the boundary contract

H.5.3 Timeout behavior (optional gate)

If a timeout-mode stub is available (or latency simulation is used),
validate that time-bounded execution produces ProviderTimeoutError.

This check is intentionally contract-level and DB-agnostic.


---

## Appendix J — Day 14 (Operational hardening & evidence)

### J.1 Internal provider diagnostics logging
Evidence:
- `pytest -q tests/core/test_chat_service_timeout.py -s --log-cli-level=INFO`
- `pytest -q tests/core/test_chat_service_provider_error.py -s --log-cli-level=INFO`

Notes:
- Full exceptions are logged internally.
- Client-facing errors remain sanitized.

### J.2 Telemetry is best-effort (UsageEvent)
Evidence:
- `pytest -q tests/api/test_chat_telemetry_best_effort.py`

### J.3 Request size limit (HTTP 413)
Evidence:
- `pytest -q tests/api/test_request_size_limit.py`
Expected:
- HTTP 413
- Body: `{"detail":"Payload too large"}`

### J.4 Defensive clamps + helpers unit tests
Evidence:
- `pytest -q tests/core/test_limits_helpers.py`

Notes:
- `latency_ms` and token counters are clamped to non-negative values before persistence.

---

## Appendix K — Day 15 (Cost Awareness / MVP)

### K.1 Purpose

This appendix documents the MVP cost awareness capability.

Scope and constraints:
- Provider-agnostic estimation based on token counts
- No external calls (no live pricing), no DB access
- No changes to `/chat` contract or write-path semantics

### K.2 Implementation surface

- Pure helper: `app/core/utils/costs.py`
  - `estimate_cost(provider, input_tokens, output_tokens) -> float`
  - Unknown providers return `0.0`
  - Negative token counts are clamped to `0`
- Static pricing table in settings:
  - `Settings.cost_rates_by_provider` (cost per 1K input/output tokens)

### K.3 Reproducible evidence

**Unknown provider + stub (expected 0.0):**

```bash
python -c "from app.core.utils.costs import estimate_cost; print('unknown:', estimate_cost('unknown', 1200, 300)); print('stub:', estimate_cost('stub', 1200, 300))"
```

Expected:
```bash
unknown: 0.0
stub: 0.0
```

**Non-zero example using a demo rate (no external calls):**
Evidence:
```bash
python - <<'PY'
from app.core.settings import settings
from app.core.utils.costs import estimate_cost

settings.cost_rates_by_provider["demo"] = type("R", (), {"input_per_1k": 1.0, "output_per_1k": 2.0})()
print("demo:", estimate_cost("demo", 1000, 500))  # expected 2.0
PY
```
Expected:
```bash
demo: 2.0
```

### K.4 Regression gate
```bash
pytest -q
```

Expected:

test suite passes (warnings allowed)
```bash
- `....................... [100%]`
app/infra/schemas/conversations.py:8
  /home/<redacted>/Cursor/llm-chat-platform/app/infra/schemas/conversations.py:8: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/
    class ConversationSummary(BaseModel):

app/infra/schemas/conversations.py:18
  /home/<redacted>/Cursor/llm-chat-platform/app/infra/schemas/conversations.py:18: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/
    class MessageOut(BaseModel):

app/main.py:65
  /home/<redacted>/Cursor/llm-chat-platform/app/main.py:65: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

.venv/lib/python3.13/site-packages/fastapi/applications.py:4576
  /home/<redacted>/Cursor/llm-chat-platform/.venv/lib/python3.13/site-packages/fastapi/applications.py:4576: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## Appendix L — Day 16: Structured JSON Logging

### L.1 Purpose

Provide cloud-friendly structured logging (JSON) with request correlation, without logging bodies and without affecting `/chat` semantics.

### L.2 Reproducible evidence

Command:

```bash
pytest -q tests/api/test_structured_logging.py -s --log-cli-level=INFO
```

Expected output shape:

One JSON line to stdout with:

request_id, path, method, status, latency_ms, app_env

Example:
```bash
{"request_id":"...","path":"/health","method":"GET","status":200,"latency_ms":1,"app_env":"development"}
```

## Appendix M — Day 17 (Offline Cost Analytics Pipeline)

### M.1 Evidence

```bash
docker compose exec -T -w /app/app api sh -lc \
  'PYTHONPATH=/app/app python scripts/export_usage_events.py --limit 2000'

docker compose exec -T -w /app/app api sh -lc \
  'PYTHONPATH=/app/app python app/scripts/run_cost_report.py --in reports/usage_events.jsonl'
```

M.2 Expected output:
```bash
[OK] exported 42 usage_events -> reports/usage_events.jsonl
=== Cost Report (offline) ===
events_total=42
estimated_cost_total=0.000000

-- Cost by provider --
manual-test cost=0.000000 events=1
stub cost=0.000000 events=37
test cost=0.000000 events=4

-- Cost by status --
error cost=0.000000 events=18
ok cost=0.000000 events=4
success cost=0.000000 events=20

-- Cost by day --
2026-01-14 cost=0.000000
2026-01-15 cost=0.000000
2026-01-16 cost=0.000000
2026-01-20 cost=0.000000
2026-01-28 cost=0.000000
2026-01-29 cost=0.000000
```
M.3 Notes
* DB column is timestamp (verified via \d+ usage_events)
* Output files are written under /app/app/reports/ (gitignored).

## Appendix N — Day 18 (Cost Analytics Artifacts)

### N.1 Purpose

Elevate the offline cost analytics pipeline to produce **reproducible, portfolio-grade artifacts**
without modifying the runtime system:

- read-only processing
- no database schema changes
- no Alembic changes
- no changes to `/chat`
- no external calls (no live pricing)
- standard library only (no pandas)

### N.2 Reproducible commands (canonical)

Export a UsageEvent sample as JSONL:

```bash
docker compose exec -T -w /app/app api sh -lc \
  'PYTHONPATH=/app/app python scripts/export_usage_events.py --limit 2000'

```

Generate offline cost reports (console + CSV artifacts):
```bash
docker compose exec -T -w /app/app api sh -lc \
  'PYTHONPATH=/app/app python app/scripts/run_cost_report.py --in reports/usage_events.jsonl'

```
### N.3 Expected artifacts

The report generator writes deterministic CSV files under reports/:

* reports/cost_by_provider.csv
* reports/cost_by_status.csv
* reports/cost_by_day.csv

All CSV files:

* include a header row
* are UTF-8 encoded
* are deterministically ordered (stable sort)
* are generated automatically on every run

CLI confirmations:

* [OK] wrote reports/cost_by_provider.csv
* [OK] wrote reports/cost_by_status.csv
* [OK] wrote reports/cost_by_day.csv

### N.4 CSV schemas

cost_by_provider.csv

Columns:

* provider
* events_count
* estimated_cost

cost_by_status.csv

Columns:

* status (canonical)
* events_count
* estimated_cost

cost_by_day.csv

Columns:

day (UTC date, ISO-8601: YYYY-MM-DD)

events_count

estimated_cost

### N.5 Canonical status normalization (report-only)

The report applies a read-only canonical mapping for aggregation:

* success -> success
* ok -> success
* error -> error
* any other / unknown -> other

This mapping is internal to the report generator.
No values are modified in the database or persisted back.

### N.6 Temporal field note

Day bucketing is derived from the event timestamp field.
The canonical temporal column in the DB is timestamp (previously verified).
The report generator remains defensive and can fall back to created_at if present in JSONL exports.


---

## 3) Checklist resumido para Notion (Day 18)

- [ ] Update `scripts/run_cost_report.py` to generate CSV artifacts under `reports/`
- [ ] Add canonical status mapping for aggregation (`ok -> success`, unknown -> `other`)
- [ ] Enforce deterministic ordering:
  - [ ] providers alphabetical
  - [ ] statuses alphabetical
  - [ ] days ascending
- [ ] Keep console output + add `[OK] wrote ...` confirmations
- [ ] Document Appendix N (commands + CSV schemas + normalization rules)
- [ ] Run:
  - [ ] `docker compose exec ... export_usage_events.py --limit 2000`
  - [ ] `docker compose exec ... run_cost_report.py --in reports/usage_events.jsonl`
- [ ] Ensure `pytest -q` still passes (no runtime changes)

---

## 4) Commit message sugerido (EN)

**Technical commit**
- `feat(cost-analytics): generate deterministic CSV artifacts in offline cost report`

**Docs commit**
- `docs(appendix): add Appendix N for Day 18 cost analytics artifacts`

--- 

## Appendix O — Day 19 (Dev Ergonomics: Bind Mount + Pytest)

### O.1 Purpose

Improve developer ergonomics in the local dev environment (dev-only), without changing production runtime behavior:

- bind-mount host source code into the `api` container (no rebuild needed for code changes)
- enable `pytest -q` inside the dev container by installing `app/requirements-dev.txt` (dev-only)
- keep existing transactional guarantees and `/chat` semantics unchanged

### O.2 Reproducible commands (canonical)

Use a stable Compose project name to avoid project/context mismatches, and load dev-only credentials from a local env file.

Create a local env file (gitignored) from the example:

```bash
cp .env.dev.example .env.dev
# Edit .env.dev locally (do not commit)

Set the canonical dev project name:
```bash
export DEV_PROJECT=llm-chat-platform-dev
```
Bring up the dev stack (build dev image with test dependencies):
```bash
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml up -d --build
```

Verify bind mounts are active:
```bash
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T api sh -lc 'ls -la /app/app | head'
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T api sh -lc 'ls -la /app/tests | head'
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T api sh -lc 'ls -la /app/app/reports | head'
```

Verify Postgres connectivity (optional):
```bash
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T postgres \
  psql -U llmchat -d llmchat -c "select 1;"
```

Run test suite inside the dev container:
```bash
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T -w /app/app api pytest -q
```
## Appendix P — Day 20 (Offline Cost Pipeline Tests: Quality + Determinism)

### P.1 Purpose

Add unit tests to harden the Day 17–18 offline cost analytics pipeline:

- canonical status mapping (ok -> success, unknown -> other)
- deterministic ordering (provider/status/day)
- stable CSV schema (expected headers)
- invalid JSONL input fails with a clear error (includes line number)

### P.2 Reproducible commands (canonical)

```bash
export DEV_PROJECT=llm-chat-platform-dev

docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml up -d --build

# Full suite (tests/ + app/tests/) inside dev container
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T -w /app api pytest -q

# Only the offline pipeline tests (focused run)
docker compose -p "$DEV_PROJECT" --env-file .env.dev -f docker-compose.dev.yml exec -T -w /app api \
  pytest -q tests/test_cost_report_pipeline.py
```

### P.3 Notes
Tests run the report script against temporary JSONL inputs and a temporary output directory to keep runs isolated.

pytest.ini is bind-mounted into the dev container at /app/pytest.ini to keep testpaths and cache_dir stable across runs.

---

## Appendix Q — Day 21 (Runtime Observability: Request/Correlation IDs + Health/Readiness)

### Goal
Improve runtime operability (SRE/Platform vibes) without modifying DB schema or the `/chat` write-path.
This adds:
- Request ID + Correlation ID propagation (headers + JSON logs)
- Liveness and readiness endpoints (read-only)
- Minimal test coverage

### Q.1 Request ID + Correlation ID

**Headers**
- If request includes `X-Request-ID`, use it as-is.
- Otherwise generate a UUID as `X-Request-ID`.
- If request includes `X-Correlation-ID`, preserve it.
- Otherwise default `X-Correlation-ID = X-Request-ID`.

**Propagation**
- Both IDs are returned in response headers for every HTTP request.
- IDs are included in structured JSON access logs (top-level fields `request_id`, `correlation_id`).

**Repro checks**
```bash
# Preserves incoming IDs
curl -sS -D - -o /dev/null \
  -H "X-Request-ID: req-123" \
  -H "X-Correlation-ID: corr-456" \
  http://localhost:8001/openapi.json

# Generates IDs when missing (expect UUID values)
curl -sS -D - -o /dev/null http://localhost:8001/openapi.json

# Verify logs include request_id + correlation_id
docker compose logs -n 50 api
```
### Q.2 Health / Readiness endpoints

Liveness

GET /healthz

Always returns 200 OK

No DB / Redis calls (safe for liveness probes)

Readiness (best-effort)

GET /readyz

Performs on-demand checks with short timeouts

Returns:

200 OK when checks pass

503 Service Unavailable when any check fails

Never affects /chat and never performs checks on startup

Repro checks
```bash
curl -i http://localhost:8001/healthz
curl -i http://localhost:8001/readyz
```

### Run in dev container:
```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /app/app api python -m pytest -q
```
Expected:

Tests validate request/correlation IDs in headers

GET /healthz returns 200 without DB calls (unit/integration)

GET /readyz returns 200/503 using mocked readiness checker

---

## Appendix R — Day 22 (Real Provider MVP: OpenAI behind feature flag, no streaming)

### R.1 Goal
Integrate a real LLM provider without changing the `/chat` public contract or breaking write-path atomicity.
Provider selection is controlled via environment variables. No streaming is introduced.

### R.2 Environment variables
- `PROVIDER` (default: `stub`)
  - `stub` | `openai` | `bedrock`
- `PROVIDER_TIMEOUT_S` (default: `12.0`)
- `OPENAI_API_KEY` (required only when `PROVIDER=openai`)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)
- `STUB_PROVIDER_MODE` (default: `ok`)
- `STUB_SIMULATED_LATENCY_MS` (default: `0`)
- `DATABASE_URL` (required for local dev; must match the Postgres container credentials)

### R.3 Local run (dev compose)
Bring up the dev stack:

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml ps
```

Health/readiness:
```bash
curl -sS http://localhost:8001/healthz && echo
curl -sS http://localhost:8001/readyz && echo
```

### R.4 Database migrations (after resetting volumes)
If you recreate the Postgres volume (e.g. docker compose down -v), you must re-apply migrations:
```bash
If you recreate the Postgres volume (e.g. docker compose down -v), you must re-apply migrations:
```

### R.5 Manual /chat smoke (no streaming)
Stub provider (default):
```bash
curl -sS -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}' | jq
  ```
  Expected: status=success and non-null conversation_id, user_message_id, assistant_message_id.

### R.6 OpenAI provider (real, no streaming)

Set env vars (do not commit secrets):
```bash
export PROVIDER=openai
export OPENAI_API_KEY="***"
export OPENAI_MODEL="gpt-4o-mini"
export PROVIDER_TIMEOUT_S="30.0"
```

Recreate the API container to apply env:
```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate api
```
Smoke:
```bash
curl -sS -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}' | jq
```
Expected behavior:

status=success when OPENAI_API_KEY is set and valid

status=error with a short safe message when the provider is not configured or fails

Response headers include X-Request-ID and X-Correlation-ID, and request_id in the JSON body matches X-Request-ID

### R.7 Notes

Changing Postgres credentials after the database volume is initialized will not update the internal user password. In dev, prefer recreating volumes (docker compose down -v) and re-running migrations.

Provider errors are normalized and sanitized; secrets and upstream payloads are not returned to clients.
```bash
::contentReference[oaicite:0]{index=0}
```
Note: If your OpenAI account has no active billing/quota, calls may return rate-limit/quota errors (handled as `status=error` with a sanitized message).


## Appendix S — Day 23 (Read-only Conversation Inspection Endpoints)

### S.1 Purpose

Add production-style, read-only endpoints to inspect conversations and messages without modifying:
- `/chat` transactional write-path
- database schema / Alembic migrations
- atomicity guarantees

### S.2 Endpoints

1) `GET /conversations/{conversation_id}`

- 404 if not found
- Returns conversation metadata and messages ordered by `(created_at ASC, id ASC)`
- Implementation uses two queries (conversation + messages) to avoid N+1 behavior

2) `GET /conversations`

- Pagination: `limit` (default 20, max 100), `offset` (default 0)
- Returns conversation metadata plus `message_count`
- Uses a single aggregated query (`COUNT(messages.id)`) and does not load message content

### S.3 Implementation surface

- `app/services/conversation_query_service.py`
  - Read-only SQLAlchemy async queries only
  - No FastAPI/HTTP semantics
- `app/schemas/conversations.py`
  - Response models for read-path endpoints
- `app/api/routes/conversations.py`
  - Thin HTTP layer calling query service

### S.4 Repro commands

```bash
pytest -q tests/api/test_conversations_read_endpoints.py
```
Manual smoke:
```bash
curl -sS http://localhost:8001/conversations | jq
curl -sS http://localhost:8001/conversations/<conversation_id> | jq
```
### S.5 Invariants preserved

/chat remains the only write-path

No schema changes

Read-only endpoints do not affect atomicity or telemetry behavior

Structured logging and request_id propagation remain unchanged (middleware-based)


## Appendix T — Day 24 (Provider Hardening: Retry & Structured Provider Logging)

T.1 Purpose

Introduce resilience and production-grade observability at the provider boundary,
without modifying:

/chat transactional semantics

database schema

Alembic migrations

ProviderPort contract surface

Scope is strictly confined to the OpenAI provider adapter layer.

T.2 Retry Policy (Controlled Backoff)

The OpenAI provider now executes through retry_async(...)
using a configurable RetryPolicy.

Configuration surface (OpenAIProviderConfig):

max_attempts

backoff_base_ms

backoff_max_ms

timeout_s

Retry is applied only for transient conditions:

ProviderErrorKind.rate_limit

ProviderErrorKind.upstream

ProviderErrorKind.timeout

Non-retryable:

ProviderErrorKind.auth

ProviderErrorKind.unknown

other 4xx client errors

Design intent:

No infinite loops

No hidden implicit retries

Explicit retry boundary

T.3 HTTP + Transport Error Normalization

All upstream failures are normalized into ProviderError
before crossing the provider boundary.

Mapping rules:

Condition	ProviderErrorKind
401 / 403	auth
429	rate_limit
5xx	upstream
TimeoutException	timeout
Network / Connect errors	upstream
Other	unknown

Guarantees:

No raw httpx exceptions escape

No provider payload leakage

No API keys exposed

Stable domain-level error contract

T.4 Structured Provider Logging Events

The provider emits structured JSON logs with safe metadata.

Events emitted:

provider.request

provider.retry

provider.response

provider.error

provider.total

Included fields (safe):

provider

model

request_id

messages_count

attempt

max_attempts

status_code

latency_ms

error_kind

retryable

Explicitly NOT logged:

message content

prompt payload

raw provider responses

API keys

This ensures production-grade observability
while preserving strict data safety.

T.5 Reproducible Evidence

Run full suite (stub mode):
```bash
docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q
```

Expected:

All tests pass
Provider retry tests validated
Provider error normalization tests validated
Structured provider logging tests validated

Optional log inspection:
```bash
docker compose logs -n 50 api
```
Expected log events include:
```bash
provider.request
provider.response
provider.retry
provider.error
provider.total
```

T.6 Architectural Impact

Day 24 completes the provider evolution:
Day 11 → abstraction introduced
Day 14 → operational guardrails
Day 22 → real provider (MVP)
Day 24 → resilience + structured logging hardening

The Provider layer now acts as a hardened isolation boundary
between external LLM APIs and core application logic.

No public API changes.
No schema changes.
No write-path changes.

----

## Appendix U — Day 25 (Streaming SSE + Minimal UI)

### U.1 Goal

Add streaming SSE to `POST /chat` behind `stream=true`, without breaking the non-stream contract,
without schema changes, and preserving write-path invariants.
Also add a minimal single-file HTML UI for local demo.

### U.2 SSE contract

When `stream=true`, `POST /chat` returns `Content-Type: text/event-stream` and emits:

- `event: token`
  - `data: <string chunk>`
- `event: done`
  - `data: {"request_id":"...","conversation_id":"...","user_message_id":"...","assistant_message_id":"...","status":"success"}`
- `event: error`
  - `data: {"error_kind":"<kind>","retryable":<bool>}`

### U.3 Persistence semantics (stream mode)

- Provider streaming happens outside any DB transaction.
- After the provider finishes, the server opens a single DB transaction and persists:
  - conversation (create/validate)
  - user message
  - assistant message (full accumulated content)
  - usage event (best-effort)
- If `conversation_id` is invalid, streaming emits `event:error` (cannot switch to an HTTP 404 after streaming begins).

### U.4 Demo UI

A minimal HTML page is served at `GET /ui` (excluded from OpenAPI schema).
The page performs a streaming `POST /chat` request using `fetch()` and parses SSE lines from the response body.

### U.5 Repro commands

Canonical green test command:

```bash
docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q
```
Smoke streaming test:
```bash
pytest -q tests/api/test_chat_streaming.py
```
Run the API:
```bash
docker compose -f docker-compose.dev.yml up -d --build api
```
Open the UI:

http://localhost:8001/ui (if port publishing works on your host)

Otherwise, use container IP:
```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' llm-chat-platform-dev-api-1
```
Then open: http://<IP>:8000/ui

Optional manual SSE smoke:
```bash
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' llm-chat-platform-dev-api-1)
curl -N --no-buffer -X POST http://$IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","stream":true}'
  ```

### Streaming validation

Canonical test command:

```bash
docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q
```

Example curl:

```bash
curl -N -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","stream":true}'
```

Expected SSE events:

- `event: token`
- `event: done`
- `event: error`

Note: the stub provider supports simulated latency via `STUB_SIMULATED_LATENCY_MS`.

### Streaming troubleshooting

Symptom:

- `event: error`
- `data: {"error_kind":"internal"}` with `PROVIDER=openai`

Cause:

- incorrect streaming fallback masked provider errors and silently diverted execution to the non-stream path

Resolution:

- ensure the streaming path uses `ProviderStreamSession` when available and does not swallow provider exceptions

Validation:

- run the `curl -N` streaming test and confirm that `event: token` is emitted before `event: done`
- provider-to-provider fallback is valid only before the first emitted token
- once any token has been emitted, the stream must terminate with `event:error` instead of switching providers

### U.6 Artifacts / files

* app/api/routes/chat.py — streaming branch and SSE generator
* app/api/routes/ui.py — serves the UI page
* app/static/chat.html — minimal UI
* tests/api/test_chat_streaming.py — streaming SSE smoke test
----

## Appendix V — Day 28 (AWS Bedrock via Existing Provider Abstraction)

### V.1 Goal

Introduce AWS Bedrock as the second real provider without changing:

- database schema
- `ChatService` contract
- `/chat` request/response schema
- streaming persistence semantics

### V.2 Configuration surface

- `PROVIDER=bedrock`
- `BEDROCK_REGION` (required)
- `BEDROCK_MODEL` (required)
- `BEDROCK_PROMPT_VERSION` (default: `v1`)
- `BEDROCK_MAX_ATTEMPTS`
- `BEDROCK_BACKOFF_BASE_MS`
- `BEDROCK_BACKOFF_MAX_MS`
- optional explicit AWS credentials:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_SESSION_TOKEN`

### V.3 Provider normalization

`BedrockProvider` preserves the existing provider boundary:

- `generate()` returns a normalized `ProviderResult`
- `stream()` returns `ProviderStreamSession`
- output text is normalized from Bedrock content blocks
- usage is normalized from Bedrock usage metadata
- `model_version` is the configured Bedrock model id
- `prompt_version` is the configured Bedrock prompt version

### V.4 Error and retry boundary

Bedrock-specific failures are mapped into existing provider error kinds:

- auth
- rate_limit
- bad_request
- timeout
- upstream
- unknown

Retry remains adapter-local and is only applied to retryable provider failures.
No raw AWS payloads, request bodies, or secrets are propagated upstream.

### V.5 Validation

Focused regression command:

```bash
.venv/bin/pytest -q tests/core/test_bedrock_provider.py tests/core/test_provider_factory.py tests/core/test_settings_provider_config.py
```

Expected:

- Bedrock provider generate normalization passes
- Bedrock provider stream normalization passes
- Bedrock error normalization passes
- provider factory returns `BedrockProvider` only when required config is present
- settings validation accepts/rejects Bedrock config as documented

## Appendix W — Day 29 (Minimal Provider Resilience Layer)

### W.1 Goal

Add a minimal provider resilience layer for MVP hardening without changing:

- database schema
- `/chat` request/response contract
- `ChatService` provider abstraction
- streaming persistence semantics

### W.2 Configuration surface

- `PRIMARY_PROVIDER=stub|openai|bedrock`
- `FALLBACK_PROVIDER=stub|openai|bedrock`
- `PRIMARY_PROVIDER` takes precedence over `provider`
- `FALLBACK_PROVIDER` takes precedence over `fallback_provider`

### W.3 Retry and fallback boundary

- retry remains confined to provider execution
- retry applies only to transient normalized failures:
  - `rate_limit`
  - `upstream`
  - `timeout`
- auth and invalid-request failures are not retried and do not trigger fallback
- fallback is single-hop only:
  - primary provider -> fallback provider

### W.4 Streaming constraint

- fallback is allowed only if the active provider fails before the first emitted token
- after any token has been emitted, fallback is not allowed
- after partial emission, the stream must terminate with `event:error`

### W.5 Validation

Focused regression command:

```bash
.venv/bin/pytest -q tests/core/test_resilient_provider.py tests/core/test_provider_factory.py tests/core/test_settings_provider_config.py tests/core/test_bedrock_provider.py tests/core/test_retry.py tests/core/test_openai_provider_retry.py tests/core/test_chat_service_contract.py tests/api/test_chat_streaming.py
```

Expected:

- retry coverage passes for transient provider failures
- fallback coverage passes for retryable exhaustion
- non-retryable failures do not trigger fallback
- streaming fallback occurs only before first token
- partial stream failures propagate terminal error without fallback
- settings precedence matches documented primary/fallback behavior

**End of appendix — complements the live LLD document**
