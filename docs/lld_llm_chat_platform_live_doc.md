# Low Level Design (LLD)

## LLM Chat Platform

**Status:** Stable baseline — validated up to Day 12

---

## 0. Change log (high level)

### Day 5–6 (Persistence foundations)

* PostgreSQL connectivity stabilized
* SQLAlchemy 2.0 async engine/session baseline
* Alembic env configured for async SQLAlchemy
* Docker Compose baseline established

### Day 7 (Core persistence models)

* `conversations` + `messages` introduced
* Message role enum stabilized (`user|assistant|system`)
* Ordering/index strategy defined

### Day 8 (Minimal telemetry)

* `usage_events` introduced and stabilized
* Best-effort usage logging pattern validated
* Alembic chain integrity preserved (no multiple active heads)

### Day 9 (Transactional chat write path)

* `/chat` upgraded from stub-only to full write path:

As of Day 9, the `/chat` endpoint implements a fully transactional write-path,
persisting conversations, messages, and usage events atomically.


### Day 10–12 (Traceability + Provider abstraction + /chat integration)

request_id end-to-end

ProviderPort/StubProvider/ChatService

/chat delegates to ChatService (atomicity preserved)

endpoint smoke evidence (success + rollback)

---

## 1. Purpose of this document

This Low Level Design (LLD) documents the **actual implemented architecture** of the LLM Chat Platform up to **Day 9**.

It is intentionally:

* Implementation-driven (not aspirational)
* Consistent with decisions taken under real execution constraints
* Suitable for senior technical review

This document evolves with the codebase.

---

## 2. Scope

### In-scope (implemented)

* API service built with FastAPI
* PostgreSQL persistence with SQLAlchemy 2 async
* Alembic migration chain stabilized and reproducible
* DEV/PROD environment split
* `/health` endpoint
* `/chat` endpoint with a transactional write-path
* Minimal LLMOps telemetry (`usage_events`)

### Out-of-scope (explicit non-goals as of Day 9)

* Real LLM provider integration
* Streaming responses
* Background workers / queues
* Authentication, authorization
* Quotas, rate limiting
* Metrics aggregation dashboards

---

## 3. Architectural goals

* Build a **correct, traceable and evolvable** chat backend
* Separate **runtime** concerns from **operational** responsibilities
* Ensure **database integrity and auditability** from day one
* Avoid premature abstractions while keeping extension points explicit

---

## 4. Tech stack

* FastAPI (async)
* PostgreSQL
* Redis (reserved for ephemeral / future use)
* SQLAlchemy 2.0 async
* Alembic
* Docker + Docker Compose

---

## 5. Glossary

* **Write-path**: the set of DB writes performed during a request.
* **Happy path**: a successful request execution.
* **Best-effort logging**: telemetry attempts that must never break the main business path.
* **Chain integrity (Alembic)**: the migration graph resolves deterministically from repo to DB.

---

## 6. Environment separation

### 6.1 Production

* Immutable Docker image
* Application code copied via:

```dockerfile
COPY app /app/app
```

* No bind mounts
* Deterministic runtime

### 6.2 Development

* `docker-compose.dev.yml`
* Bind mount: `./app:/app/app`
* Host UID/GID propagation
* Enables rapid iteration on:

  * ORM models
  * Alembic revisions
  * import paths

### 6.3 Scripts

* `scripts/dev_up.py` — bring up dev overlay
* `scripts/dev_down.py` — bring down dev overlay

---

## 7. Repository structure

Reference structure (may evolve, but invariants remain):

```
app/
  main.py
  api/
    ops.py
    routes/
      chat.py
  schemas/
    chat.py
  models/
    conversation.py
    message.py
    usage_event.py
  infra/
    db/
      base.py
      session.py
  services/
    usage_logger.py

alembic/
  env.py
  versions/

scripts/
  dev_up.py
  dev_down.py

Dockerfile
.env.example
README.md
LLD.md
alembic.ini
docker-compose.yml
docker-compose.dev.yml
```

---

## 8. Configuration strategy

### 8.1 Single source of truth

* `settings.database_url` is authoritative
* Both runtime and Alembic resolve DB URL from the same settings

### 8.2 Environment variables (typical)

* `APP_ENV`: `development|production`
* `LOG_LEVEL`: `INFO|DEBUG|...`
* `DATABASE_URL`: `postgresql+asyncpg://...`
* `REDIS_URL`: `redis://...` (reserved)

---

## 9. Database layer

### 9.1 Engine and session

* SQLAlchemy 2.0 async engine
* `AsyncSession` provided via FastAPI dependency injection

### 9.2 Transaction boundaries

* Explicit boundaries using:

```python
async with db.begin():
    ...
```

Design intent:

* Business writes happen as one atomic unit
* Telemetry can be coupled to business writes (happy path)
* Telemetry must decouple on error paths

---

## 10. Data model

### 10.1 conversations

Represents a logical chat session.

Fields:

* `id: UUID (PK)`
* `created_at`
* `updated_at`
* `title` (nullable)
* `metadata` (nullable, JSONB)

Semantics:

* Created lazily on first message
* Acts as aggregation root for messages

### 10.2 messages

Represents a message inside a conversation.

Fields:

* `id: UUID (PK)`
* `conversation_id: UUID (FK -> conversations.id)`
* `role: enum(user|assistant|system)`
* `content: text`
* `created_at`

Indexes:

* `(conversation_id, created_at)` for ordered retrieval

Semantic contract:

* `user`: human input
* `assistant`: model output
* `system`: control context

### 10.3 usage_events

Minimal LLMOps telemetry entity.

Fields:

* `id: UUID (PK)`
* `provider: text`
* `model_version: text`
* `prompt_version: text`
* `request_id: UUID (nullable)`
* `conversation_id: UUID (nullable FK)`
* `message_id: UUID (nullable FK)`
* `input_tokens: int (nullable)`
* `output_tokens: int (nullable)`
* `total_tokens: int (nullable)`
* `latency_ms: int (nullable)`
* `status: text` (current: `success|error`; legacy may exist)
* `error_message: text (nullable)`
* `timestamp/created_at: timestamptz`

Indexes (expected / implemented):

* `request_id`
* `(conversation_id, timestamp)`
* `message_id`

Design intent:

* Capture who/what/when/how-long/result
* Foundation for observability and auditability

---

## 11. Alembic migration strategy

### 11.1 Rules

* Migrations are **operational**, never automatic at runtime
* Canonical execution environment is the `api` container

### 11.2 Chain integrity

Invariants:

* Single active head
* Historical branchpoints preserved via no-op revisions
* Merge revisions recorded

Practical consequence:

* All files under `alembic/versions/` must be committed
* Rebuilding images without committed revisions can desynchronize:

  * DB `alembic_version`
  * repository migration graph

### 11.3 Canonical commands

```bash
docker compose exec -T -w /app/app api alembic current
```

```bash
docker compose exec -T -w /app/app api alembic heads
```

```bash
docker compose exec -T -w /app/app api alembic upgrade head
```

---

## 12. API layer

### 12.1 Application entrypoint

* `app/main.py` defines:

  * logging configuration
  * FastAPI instance
  * router inclusion

### 12.2 Routers

* `/health` (process-level liveness)
* `/chat` (core write path)

Routers are:

* included explicitly in `main.py`
* prefixed at inclusion time

---

## 13. Schemas (Pydantic)

### 13.1 ChatRequest

Fields:

* `conversation_id: UUID | None`
* `message: str` (required)

Validation policy:

* `message` is required
* extra fields are rejected (strict)

### 13.2 ChatResponse

Fields:

* `request_id: UUID`
* `conversation_id: UUID`
* `user_message_id: UUID | None`
* `assistant_message_id: UUID | None`
* `assistant_content: str | None`
* `status: success|error`
* `error_message: str | None`

---

## 14. `/health` endpoint

### 14.1 Contract

`GET /health`

* Confirms process is alive
* Does not validate Postgres/Redis directly
* Dependency readiness handled via Docker healthchecks

---

## 15. `/chat` endpoint (Day 9 design)

### 15.1 Responsibilities

* Generate `request_id`
* Create or validate `Conversation`
* Persist user message
* Execute model logic (currently stub)
* Persist assistant message
* Persist UsageEvent

All inside a single DB transaction.

### 15.2 Execution order (strict)

1. Start timer
2. Generate `request_id`
3. `async with db.begin()`
4. Resolve conversation
5. Insert `Message(role=user)`; flush
6. Execute model (stub)
7. Insert `Message(role=assistant)`; flush
8. Insert `UsageEvent` (FKs valid)
9. Commit transaction
10. Return response

### 15.3 Use of `flush()`

`flush()` is used to ensure:

* primary keys are materialized
* FK constraints can be satisfied
* ordering is deterministic

Important:

* `flush()` does not commit
* commit occurs when transaction ends successfully

### 15.4 Error handling policy

On unexpected exceptions:

* enforce rollback
* record best-effort error UsageEvent without FKs
* re-raise exception

Rationale:

* avoids “error while logging the error”
* decouples observability from business data success

#### Input guardrails and execution boundaries (Day 12)

The `/chat` write-path enforces **early guardrails** and **explicit execution boundaries**
to protect both persistence integrity and provider isolation.

**Input-level guardrails (A2):**

- Blank or whitespace-only messages are rejected at schema validation level
- Maximum message length is enforced at schema level (`MAX_MESSAGE_CHARS`)
- Requests exceeding maximum payload size are rejected by HTTP middleware
  (`RequestSizeLimitMiddleware`) *before* reaching application logic

These checks ensure that invalid or abusive input never enters:
- the database transaction
- the provider execution boundary

**Execution-level guardrails (A3):**

- Provider execution is wrapped by `ChatService` with an explicit timeout
- Provider failures are normalized into domain errors:
  - `ProviderTimeoutError`
  - `ProviderExecutionError`
- Provider internals and raw exceptions are never leaked across the service boundary

Design rationale:

- Guardrails fail fast and deterministically
- Business transactions remain atomic
- Telemetry must never break the main execution path
- Provider instability cannot corrupt persistence state


### 15.5 Stub provider semantics

* Deterministic response: `"stub: provider not configured yet"`
* No external LLM calls
* No token accounting

The stub exists to validate the persistence + telemetry pipeline before provider integration.

### 15.6 Update — Day 12: ChatService integration

* delegate to ChatService
* UsageEvent success use ProviderResult metrics
*error path: provider error → rollback + best-effort usage_event without FKs

UsageEvent success usa ProviderResult metrics

error path: provider error → rollback + best-effort usage_event sin FKs

---

## 16. Observed failure modes (and resolutions)

### 16.1 Missing `/chat` in OpenAPI

Cause:

* router import/inclusion inconsistencies

Resolution:

* single authoritative router file
* explicit inclusion in `main.py`

### 16.2 Import-time crash in Docker

Cause:

* stale imports pointing to non-existent modules

Resolution:

* removed ambiguous paths
* enforced explicit `app.api.routes.chat`

### 16.3 FK violations when logging usage events

Cause:

* usage logging attempted with conversation_id that did not exist (rolled back / not created)

Resolution:

* usage event on success inside the same transaction
* error usage events without FKs

### 16.4 Indentation/syntax errors halting container

Cause:

* indentation error after `except` statement

Resolution:

* strict formatting and container log verification

---

## 17. Operational workflows

### 17.1 Standard bring-up

```bash
cp .env.example .env
docker compose up -d
```

### 17.2 DEV bring-up (bind mounts)

```bash
./scripts/dev_up.py
```

### 17.3 Verify migrations

```bash
docker compose exec -T -w /app/app api alembic current
```

```bash
docker compose exec -T -w /app/app api alembic heads
```

### 17.4 Verify chat write path

```bash
curl -s -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}' | jq
```

DB verification:

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select role, count(*) from messages group by role order by role;"
```

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select provider, status, conversation_id, message_id, timestamp from usage_events order by timestamp desc limit 5;"
```

---

## 18. Current guarantees (post Day 9)

* `/chat` successful requests produce:

  * `Conversation`
  * `Message(user)`
  * `Message(assistant)`
  * `UsageEvent` with FK references
* Failure does not corrupt database integrity
* Failure does not block telemetry capture (best-effort)
* Alembic chain remains reproducible

---

## 19. Next evolution steps

* Introduce provider interface abstraction (port/adapters)
* Integrate real providers (OpenAI/Bedrock/etc.)
* Add integration tests for write-path and failure modes
* Introduce streaming responses
* Introduce auth, quotas, rate limiting
* Metrics aggregation and dashboards

---

## 20. Appendix

### 20.1 Design discipline

* Keep runtime behavior deterministic
* Keep migrations explicit
* Keep traceability mandatory
* Keep changes incremental and reviewable

---
(contenido existente preservado íntegramente, se aplicarán actualizaciones incrementales sin eliminar líneas)

---

## 21. Day 10 — Read-path, Auditing, and End-to-End Traceability

### 21.1 Objective

Enable full read access, auditing, and end-to-end traceability of the system, while keeping the write-path (`POST /chat`) **fully intact** and without modifying Alembic migrations or base models.

### 21.2 Reaffirmed Invariants

* `/chat` remains a single atomic transaction
* Alembic migrations are not modified
* No tables are recreated
* Telemetry rules:

  * success → `UsageEvent` with foreign keys (`conversation_id`, `message_id`)
  * error → `UsageEvent` best-effort (foreign keys optional)
* DEV / PROD split remains intact

### 21.3 Read-path — Conversations

Implemented and validated endpoints:

* `GET /conversations`

  * pagination (`limit`, `offset`)
  * ordered by `created_at`
  * returns metadata only (no messages)

* `GET /conversations/{id}`

  * returns 404 if not found
  * loads conversation and associated messages
  * deterministic ordering (`created_at`, `id`)

### 21.4 Read-path — Usage Events (Auditing)

* `GET /usage-events`
* Functional filters:

  * `from` / `to` (ISO datetime)
  * `provider`
  * `model_version`
  * `request_id`
  * `conversation_id`
  * `status`
* Pagination (`limit`, `offset`)
* Deterministic ordering (`timestamp desc`, `id desc`)
* `timestamp` is the canonical temporal field (not `created_at`)

### 21.5 End-to-End Traceability (D1)

A complete execution reconstruction was implemented **without introducing new endpoints**, using an internal script / service.

Given a `request_id`:

* All related `UsageEvent` records are retrieved
* A `primary_event` is selected (preference: `success`)
* `conversation_id` is resolved
* Associated messages are reconstructed (`user` → `assistant`)
* Coherence is verified across:

  * input
  * output
  * provider
  * model_version
  * prompt_version

Results:

* Successful reconstruction even in edge cases (identical timestamps)
* Explicit coherence checks
* Warnings only in best-effort scenarios

### 21.6 Day 10 Closing Status

* Conversations are readable and fully reconstructible
* UsageEvents are queryable and auditable
* End-to-end traceability is defensible
* Development infrastructure is robust
* Write-path remains 100% untouched

---

**Document updated up to Day 11.**


---

## 22. Provider Abstraction & DB-agnostic Orchestration (Day 11)

### 22.1 Objective

Introduce a provider abstraction layer and an orchestration service that remain fully decoupled from:

- FastAPI / HTTP concerns
- SQLAlchemy / database persistence
- Alembic migration chain

This prepares the system for real LLM provider integration without contaminating the transactional write-path (`POST /chat`).

### 22.2 ProviderPort contract (async-first)

A provider is modeled as an async-first port:

- `ProviderPort.generate(input: ProviderInput) -> ProviderResult`

**ProviderInput (domain-only)**

- `request_id` (UUID): correlation id, propagated end-to-end
- `messages`: domain `ChatMessage[]` (provider-agnostic)
- optional runtime hints: `temperature`, `max_tokens`, `metadata`

**ProviderResult (domain-only)**

- `content` (generated text)
- required metadata: `provider`, `model_version`, `prompt_version`
- optional metrics: `input_tokens`, `output_tokens`, `total_tokens`, `latency_ms`
- optional `raw` payload for local debugging (not persisted by default)

**Non-goals**

- ProviderResult intentionally does **not** carry DB foreign keys (`conversation_id`, `message_id`)
- `status` is not a provider concern; it is a write-path concern and is determined by request execution outcome

Rationale: preserve best-effort telemetry rules and keep observability decoupled from business-data success.

### 22.3 StubProvider (deterministic, no IO)

A deterministic stub provider is implemented to validate the contract before integrating real providers:

- deterministic output derived from `request_id` + last input message
- configurable simulated latency
- configurable deterministic error mode
- no external IO and no persistent side effects

### 22.4 ChatService (pure orchestration)

`ChatService` orchestrates:

- input messages → provider invocation → assistant output message

Rules:

- no database access
- no transaction management
- no FastAPI/HTTP semantics

The service returns a `ChatServiceResult` containing:

- `request_id`
- `assistant_message` (domain message to be persisted later by `/chat`)
- `provider_result` (metadata/metrics used later for `UsageEvent` emission)

- now is integrated on /chat

**Execution boundary guarantees (Day 12):**

- `ChatService` is the exclusive execution boundary for providers
- All provider calls are:
  - time-bounded
  - exception-normalized
  - isolated from persistence concerns

`ChatService` guarantees that:

- successful execution returns a valid `ChatServiceResult`
- timeouts raise `ProviderTimeoutError`
- provider failures raise `ProviderExecutionError`
- raw provider exceptions never cross the boundary

This allows `/chat` to reason only in terms of:
- success vs error
- rollback vs commit
- telemetry emission strategy


### 22.5 Evidence (runners and tests)

Reproducibility artifacts:

- `app/scripts/run_stub_chat.py` (ok path + error path)
- `app/scripts/run_stub_determinism.py` (determinism + sensitivity checks)
- contract tests (no DB):
  - `app/tests/core/test_stub_provider_contract.py`
  - `app/tests/core/test_chat_service_contract.py`

Integration with `/chat` is intentionally deferred to the next iteration, after the contract surface is validated.

* run_chat_endpoint_smoke.py
* run_chat_endpoint_error_smoke.py

Additional evidence (Day 12):

- API guardrail tests:
  - `tests/api/test_chat_guardrails.py`
    - rejects blank messages
    - rejects oversized messages
- Contract-level timeout and error propagation tests:
  - `test_chat_service_contract.py`
    - provider timeout handling
    - provider error normalization


---

## Addendum — Day 14: Operational hardening & evidence

Day 14 focused on strengthening operational robustness and reproducibility
without modifying architectural invariants or public contracts.

### Scope

The following guarantees were reinforced:

* `/chat` remains the single transactional write-path
* No database schema or Alembic changes were introduced
* Provider abstraction and DB-agnostic boundaries remain unchanged

### Changes

* Internal diagnostic logging added at provider boundaries
  * Full exception traces are logged internally
  * Client-facing responses remain sanitized
* Best-effort telemetry hardened
  * Telemetry failures never break the `/chat` request
  * Defensive clamping applied to latency and token metrics
* Request guardrails extended
  * Payload size limits enforced at middleware level
  * Explicit `413 Payload Too Large` behavior validated via tests

### Evidence

Reproducible evidence and verification commands are documented in
`lld_apendix.md`, including:

* Provider timeout and execution error logging
* Telemetry best-effort behavior under failure
* Request size limit enforcement



## Appendices

Detailed execution-level documentation, debugging playbooks, and deep technical references
are maintained in a separate companion document:

- **LLD Appendix — LLM Chat Platform (Debug & Deep Dive)**

This separation is intentional to keep the core LLD focused on architecture and decisions,
while allowing the appendix to evolve with operational learnings and real-world failures.


**This document reflects the state of the system up to **Day 12**.
**Execution-level details and debugging notes are tracked in the Appendix.**