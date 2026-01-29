# LLD Appendix — LLM Chat Platform

**Companion document to:** `lld_llm_chat_platform_live_doc.md`

**Scope:** Deep technical appendices, debugging playbooks, and execution-level details

**Validity:** Up to Day 10 (Appendix F)

> Note: Appendices A–E describe the effective system state up to Day 9.
> Appendix F documents the Day 10 traceability layer, implemented as a read-only reconstruction mechanism.

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



**End of appendix — complements the live LLD document**