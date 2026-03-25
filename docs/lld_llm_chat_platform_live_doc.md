# Low Level Design (LLD)

## LLM Chat Platform

**Status:** Stable baseline — validated up to Day 25 (Streaming SSE + Minimal UI + Stable async tests)

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

This Low Level Design (LLD) documents the **actual implemented architecture** of the LLM Chat Platform up to **Day 25**.

It is intentionally:

* Implementation-driven (not aspirational)
* Consistent with decisions taken under real execution constraints
* Suitable for senior technical review
* Updated incrementally to preserve historical design context

This document evolves with the codebase.

---

## 2. Scope

### In-scope (implemented)

* API service built with FastAPI
* PostgreSQL persistence with SQLAlchemy 2 async
* Alembic migration chain stabilized and reproducible
* DEV/PROD environment split
* Liveness and readiness endpoints
* `/chat` endpoint with transactional persistence semantics
* Streaming SSE on `POST /chat` behind `stream=true`
* Minimal demo UI served at `GET /ui`
* Read-only inspection endpoints for conversations and usage events
* Minimal LLMOps telemetry (`usage_events`)
* Provider abstraction with validated stub plus hardened OpenAI and Bedrock adapters

### Out-of-scope (explicit non-goals as of Day 25)

* Full frontend application / SPA / build pipeline
* Background workers / queues
* Authentication, authorization
* Quotas, rate limiting
* Metrics aggregation dashboards
* Additional provider implementations beyond the current validated surface

---

## 3. Architectural goals

* Build a **correct, traceable and evolvable** chat backend
* Separate **runtime** concerns from **operational** responsibilities
* Ensure **database integrity and auditability** from day one
* Avoid premature abstractions while keeping extension points explicit

### 3.1 Runtime architecture

#### Layers

* API layer (FastAPI routers) — request validation, HTTP semantics, streaming SSE
* Domain layer — `ChatService` orchestration and provider contract
* Infrastructure layer — SQLAlchemy async session lifecycle, persistence wiring, and DB models
* Provider layer — validated stub provider plus hardened OpenAI and Bedrock adapters
* Observability layer — HTTP structured logs, provider structured logs, usage telemetry

#### Request correlation

* Request ID is propagated through middleware and request context
* `/chat` responses include `request_id` for traceability
* Operational analysis and trace reconstruction use `request_id` as the primary correlation key

---

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

```text
app/
  main.py
  api/
    ops.py
    runtime_ops.py
    routes/
      chat.py
      conversations.py
      usage_events.py
      ui.py
  schemas/
    chat.py
    conversations.py
  core/
    domain/
    providers/
    utils/
    settings.py
  http/
    middleware/
  infra/
    db/
    schemas/
  models/
    conversation.py
    message.py
    usage_event.py
  services/
    conversation_query_service.py
    readiness.py
    trace.py
    usage_events.py
    usage_logger.py
  static/
    chat.html
  scripts/

tests/
  api/
  core/

docs/
  lld_llm_chat_platform_live_doc.md
  lld_llm_chat_platform_live_doc_v2.md
  lld_apendix.md

---

## 8. Configuration strategy”

### 8.1 Single source of truth

* `settings.database_url` is authoritative
* Both runtime and Alembic resolve DB URL from the same settings

### 8.2 Environment variables (typical)

* APP_ENV: development|production
* LOG_LEVEL: INFO|DEBUG|...
* DATABASE_URL: postgresql+asyncpg://...
+ REDIS_URL: redis://... (reserved)
* PROVIDER: stub|openai|bedrock
* PROVIDER_TIMEOUT_S: provider execution timeout
* OPENAI_API_KEY: required when PROVIDER=openai
* OPENAI_MODEL: OpenAI model selection
* BEDROCK_REGION: required when PROVIDER=bedrock
* BEDROCK_MODEL: required when PROVIDER=bedrock
* BEDROCK_PROMPT_VERSION: normalized prompt version for Bedrock metadata
* BEDROCK_MAX_ATTEMPTS: Bedrock retry cap
* BEDROCK_BACKOFF_BASE_MS: Bedrock retry base delay
* BEDROCK_BACKOFF_MAX_MS: Bedrock retry max delay
* AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN: optional explicit AWS credentials
* STUB_PROVIDER_MODE: ok|error
* STUB_SIMULATED_LATENCY_MS: deterministic stub latency

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

* `/health` (legacy process-level liveness)
* `/healthz` (liveness)
* `/readyz` (readiness)
* `/ops/health` (operations surface)
* `/chat` (core write path; non-stream JSON by default, SSE when `stream=true`)
* `/conversations`
* `/conversations/{conversation_id}`
* `/usage-events`
* `/ui` (minimal local demo UI; excluded from OpenAPI schema)

Routers are:

* included explicitly in `main.py`
* prefixed at inclusion time where applicable
* kept thin, with orchestration and query logic delegated to domain/services layers

---

## 13. Schemas (Pydantic)

### 13.1 ChatRequest

Fields:

* `conversation_id: UUID | None`
* `message: str` (required)
* `stream: bool = False`

Validation policy:

* `message` is required
* extra fields are rejected (strict)
* non-stream mode remains the default behavior

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
* Preserved as a lightweight legacy health surface

Additional operational endpoints are also implemented:

* `GET /healthz` — liveness probe
* `GET /readyz` — readiness probe with best-effort dependency checks
* `GET /ops/health` — operations-oriented health surface

Dependency readiness is not enforced at API startup.
Runtime checks remain explicit and read-only.

---

## 15. `/chat` endpoint (evolved through Day 25)

### 15.1 Responsibilities

Non-stream mode (`stream=false`, default):

* Generate `request_id`
* Create or validate `Conversation`
* Persist user message
* Execute model logic via `ChatService`
* Persist assistant message
* Persist `UsageEvent`
* Return JSON response

Streaming mode (`stream=true`):

* Generate `request_id`
* Resolve or allocate `conversation_id`
* Stream provider output through SSE
* Accumulate assistant content in memory
* Persist conversation + messages + usage after provider completion
* Emit final SSE completion event

In both modes, `/chat` remains the only authoritative write-path.

### 15.2 Execution order (non-stream)

1. Start timer
2. Generate `request_id`
3. `async with db.begin()`
4. Resolve conversation
5. Insert `Message(role=user)`; flush
6. Execute model via `ChatService.run(...)`
7. Insert `Message(role=assistant)`; flush
8. Insert `UsageEvent` (FKs valid)
9. Commit transaction
10. Return JSON response

### 15.3 Use of `flush()`

`flush()` is used to ensure:

* primary keys are materialized
* FK constraints can be satisfied
* ordering is deterministic

Important:

* `flush()` does not commit
* commit occurs when transaction ends successfully

### 15.4 Error handling policy

On unexpected exceptions in non-stream mode:

* enforce rollback
* record best-effort error `UsageEvent` without FKs
* re-raise exception or return sanitized error semantics, depending on boundary

Rationale:

* avoids “error while logging the error”
* decouples observability from business data success
* preserves business-data atomicity even when provider execution fails



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

* Deterministic response behavior for non-stream execution
* Deterministic streaming behavior for `stream=true`
* Configurable simulated latency
* Configurable deterministic error mode
* No external LLM calls
* Token accounting may be absent or synthetic depending on test scenario

The stub exists to validate persistence, telemetry, provider contracts, and streaming semantics before relying on external providers.

### 15.6 Update — ChatService integration and provider boundary

`/chat` delegates provider execution to `ChatService`.

Rules:

* `ChatService` has no database access
* `ChatService` has no transaction control
* `ChatService` normalizes provider failures into domain-level errors
* success-path `UsageEvent` fields are derived from `ProviderResult`
* error-path telemetry remains best-effort and may omit foreign keys

This preserves a clean execution boundary between:

* HTTP layer
* transactional persistence
* provider orchestration


### 15.7 Streaming mode (Day 27B)

Streaming is opt-in via `stream=true`.

When enabled, `POST /chat` returns `Content-Type: text/event-stream` and emits:

* `event: token`
  * `data: <string chunk>`
* `event: done`
  * `data: <json>`
* `event: error`
  * `data: <json>`

#### Execution order (stream=true)

1. Resolve `request_id`
2. Resolve or allocate `conversation_id`
3. Start SSE response
4. Execute provider streaming via `ChatService.stream_chat(...)`
5. The provider returns `ProviderStreamSession`
6. Emit `token` events from `ProviderStreamSession.chunks` as chunks arrive
7. Accumulate assistant content in memory
8. After provider completion, call `ProviderStreamSession.get_final_result()`
9. Open a single DB transaction
10. Create or validate conversation
11. Persist user message
12. Persist assistant message using the full accumulated content
13. Persist `UsageEvent` best-effort
14. Emit `done`
15. End stream

#### Persistence semantics

Streaming provider execution happens outside the database transaction.

The final persistence phase still uses a single DB transaction for:

* conversation
* user message
* assistant message
* usage event (best-effort)

This preserves atomicity for database writes while avoiding long-lived transactions during streaming.

`ProviderStreamSession` exposes:

* `chunks: AsyncIterator[str]`
* `get_final_result() -> ProviderStreamResult`

`ProviderStreamResult` contains:

* `content`
* `provider_result`

`ProviderResult` is authoritative for streaming telemetry and metadata:

* `input_tokens`
* `output_tokens`
* `total_tokens`
* `model_version`
* `prompt_version`
* `latency_ms`

Downstream layers do not reconstruct these values.

#### Streaming failure handling (Day 27B fix)

`ChatService.stream_chat(...)` must not swallow provider exceptions.

Streaming fallback is only valid when a provider does not implement `stream()`.
If a provider exposes streaming, `ProviderStreamSession` is authoritative and provider errors must propagate through the streaming path instead of falling back to non-stream execution.

Streaming chunk size is not guaranteed and depends on upstream provider emission behavior.

#### Important tradeoff

The client may receive streamed tokens before the final DB transaction commits.

If final persistence fails:

* the stream emits `event: error`
* no conversation/messages are committed

#### Fallback semantics

`ChatService.stream_chat(...)` supports defensive fallback behavior only for providers that do not implement streaming.

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

## 18. Current guarantees (post Day 25)

### 18.1 Observability

#### HTTP structured logging

* One JSON log line is emitted per HTTP request
* Mandatory fields include: `request_id`, `path`, `method`, `status`, `latency_ms`, `app_env`
* Request and response bodies are not logged
* Logs are emitted to stdout

#### Provider structured logging

* The provider layer emits structured lifecycle events
* Typical events include:
  * `provider.request`
  * `provider.retry`
  * `provider.response`
  * `provider.error`
  * `provider.total`
* Logged metadata is intentionally safe and excludes user content, prompt payloads, raw provider responses, and secrets

#### Traceability

* `request_id` is propagated end-to-end
* `/chat` execution can be reconstructed deterministically from persisted business data and telemetry
* Trace reconstruction remains read-only and does not modify runtime semantics

#### Request protection

* Middleware-level request size limits protect the API process from oversized payloads
* Guardrail failures are explicit and test-validated

#### Offline analytics

* Persisted `usage_events` support read-only offline export and aggregation
* Cost estimation remains provider-agnostic and decoupled from runtime execution

### 18.1 Current guarantees (post Day 25)

* `/chat` remains the only authoritative write-path
* Non-stream mode persists business data inside one transaction
* Stream mode persists business data only after provider completion
* Successful non-stream requests produce:

  * `Conversation`
  * `Message(user)`
  * `Message(assistant)`
  * `UsageEvent` with FK references

* Successful stream requests produce the same persisted entities after streaming completes
* Failure does not corrupt database integrity
* Failure does not block telemetry capture (best-effort)
* Provider failures are normalized at the domain boundary
* Request/response observability remains non-invasive
* Alembic chain remains reproducible

---

## 19. Next evolution steps

* Harden provider configuration through centralized settings
* Reduce provider-specific environment parsing in factory code
* Improve streaming telemetry consistency
* Consider richer SSE completion payloads
* Introduce auth, quotas, and rate limiting in future controlled phases
* Expand operational documentation without changing core invariants

---

## 20. Appendix

### 20.1 Design discipline

* Keep runtime behavior deterministic
* Keep migrations explicit
* Keep traceability mandatory
* Keep changes incremental and reviewable

### 20.1 Tests (async-first)

#### Canonical green command

`docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q`

#### Test stack

* `httpx.AsyncClient`
* `ASGITransport`
* `LifespanManager` to ensure startup and shutdown hooks execute

#### Coverage targets (current)

* `/chat` non-stream regression
* Streaming SSE smoke test (`token` + `done`)
* Conversations read endpoints
* Health and readiness endpoints
* Request ID propagation
* Request size limit enforcement
* Structured logging behavior
* Telemetry best-effort behavior under failure

#### Intent

The test suite validates runtime invariants without weakening the architecture-first boundary between:

* HTTP layer
* provider orchestration
* persistence
* observability



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

**Document updated incrementally through Day 25.**


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
- `ProviderPort.stream(input: ProviderInput) -> ProviderStreamSession`

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
- deterministic streaming support
- no external IO and no persistent side effects

This makes success, failure, and streaming paths fully reproducible.

### 22.4 ChatService (pure orchestration)

`ChatService` orchestrates:

- input messages → provider invocation → assistant output message
- optional provider streaming via `ProviderStreamSession` → incremental chunk emission to the API layer and authoritative final result retrieval

Rules:

- no database access
- no transaction management
- no FastAPI/HTTP semantics

The service returns a `ChatServiceResult` containing:

- `request_id`
- `assistant_message` (domain message to be persisted later by `/chat`)
- `provider_result` (metadata/metrics used later for `UsageEvent` emission)

This service is integrated into `/chat`.

**Execution boundary guarantees:**

- `ChatService` is the exclusive execution boundary for providers
- All provider calls are:
  - time-bounded
  - exception-normalized
  - isolated from persistence concerns

`ChatService` guarantees that:

- successful execution returns a valid `ChatServiceResult`
- timeouts raise normalized provider timeout errors
- provider failures raise normalized execution errors
- raw provider exceptions never cross the boundary
- streaming mode may fall back defensively when a provider does not expose valid streaming behavior

This allows `/chat` to reason only in terms of:

- success vs error
- rollback vs commit
- telemetry emission strategy
- non-stream JSON vs streaming SSE response mode


### 22.5 Evidence (runners and tests)

Reproducibility artifacts include:

- `app/scripts/run_stub_chat.py` (ok path + error path)
- `app/scripts/run_stub_determinism.py` (determinism + sensitivity checks)
- contract tests (no DB):
  - `app/tests/core/test_stub_provider_contract.py`
  - `app/tests/core/test_chat_service_contract.py`

Later validated integration evidence includes:

- `/chat` success and rollback smoke runners
- request ID propagation tests
- readiness tests
- streaming smoke test:
  - `tests/api/test_chat_streaming.py`


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

## Addendum — Day 16: Structured JSON Logging

### Scope

Add minimal, enterprise-ready structured logging to improve observability, without changing
runtime semantics or transactional guarantees.

### Changes

* Added ASGI middleware emitting one JSON log line per HTTP request to stdout
* Mandatory fields: `request_id`, `path`, `method`, `status`, `latency_ms`, `app_env`
* No request/response bodies are logged
* Correlation uses `request_id` (state/header) or generates a UUID for logging only

### Evidence

Reproducible commands and expected output shape are documented in `lld_apendix.md`
(Appendix L — Day 16).

## Addendum — Day 17: Offline Cost Analytics Pipeline

### Scope

Introduce an offline, read-only analytics layer over persisted `usage_events`
to enable cost exploration without modifying runtime semantics.

### Changes

* Added `scripts/export_usage_events.py`
  - Read-only export of `usage_events` to JSONL
  - No write operations
* Added `scripts/run_cost_report.py`
  - Offline aggregation using `estimate_cost`
  - No database access
* Outputs written under `/app/app/reports/` (gitignored)
* No migrations introduced
* No changes to `/chat` write-path semantics

### Notes

* DB column name is `timestamp` (verified via `\d+ usage_events`)
* Export layer maps DB `timestamp` → JSON field `timestamp`
* Pipeline is deterministic and reproducible

### Evidence

Reproducible commands and expected output are documented in
`lld_apendix.md` (Appendix M — Day 17).


## Addendum — Day 24: Provider Hardening (Resilience & Structured Logging)

Scope

Day 24 introduced resilience mechanisms and structured observability
to the real OpenAI provider implementation, without modifying:

/chat transactional semantics

database schema

Alembic migration chain

ProviderPort contract surface

The changes are strictly confined to the provider adapter layer.

Retry & Backoff Policy

The OpenAI provider now executes through retry_async(...)
with a configurable RetryPolicy.

Configurable parameters (via OpenAIProviderConfig):

max_attempts

backoff_base_ms

backoff_max_ms

Retry is applied only for transient failures:

ProviderErrorKind.rate_limit

ProviderErrorKind.upstream

ProviderErrorKind.timeout

Non-retryable errors:

ProviderErrorKind.auth

ProviderErrorKind.unknown

other 4xx client errors

This ensures controlled retry behavior without infinite loops
or hidden implicit retries.

Error Normalization Boundary

All transport and HTTP errors are normalized into ProviderError
before crossing the provider boundary.

Mapping guarantees:

Condition	ProviderErrorKind
401 / 403	auth
429	rate_limit
5xx	upstream
TimeoutException	timeout
Network errors	upstream
other	unknown

Raw HTTP payloads, provider-specific exceptions,
and API keys are never propagated upstream.

This preserves a stable domain-level error contract.

Structured Provider Logging

The OpenAI provider emits structured operational logs
for resilience diagnostics and traceability.

Emitted events:

provider.request

provider.retry

provider.response

provider.error

provider.total

Safe metadata included:

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

user message content

prompt payload

raw provider responses

API keys

Design intent:

Enable production-grade observability

Maintain strict data safety guarantees

Avoid logging sensitive content

Architectural Impact

Day 24 completes the provider evolution:

Day 11 → abstraction introduced

Day 14 → operational guardrails

Day 24 → resilience + structured logging

The Provider layer now acts as a hardened isolation boundary
between external LLM APIs and core application logic.

## Addendum — Day 28: Bedrock as Second Real Provider

### Scope

Day 28 validates provider extensibility by introducing AWS Bedrock through the existing provider abstraction,
without modifying the database schema, `ChatService` contract, or `/chat` request/response schemas.

### Changes

* `PROVIDER=bedrock` is wired through `build_provider(...)`
* `BedrockProvider.generate(...)` returns normalized `ProviderResult`
* `BedrockProvider.stream(...)` returns `ProviderStreamSession`
* Bedrock usage is normalized into `input_tokens`, `output_tokens`, `total_tokens`
* `model_version` is derived from configured `BEDROCK_MODEL`
* `prompt_version` is derived from configured `BEDROCK_PROMPT_VERSION`
* Bedrock errors are normalized into existing `ProviderErrorKind` values
* Structured provider logging remains safe and provider-local

### Preserved invariants

* No provider-specific logic leaked into domain or route layers
* Streaming persistence still occurs after provider completion in one DB transaction
* `/chat` and `UsageEvent` contracts remain unchanged
* Retry behavior remains adapter-local and constrained to retryable provider failures

## Addendum — Day 25: Streaming SSE + Minimal UI

### Scope

Day 25 introduced opt-in SSE streaming on `POST /chat` and a minimal static demo UI,
without modifying database schema, Alembic migrations, or the default non-stream JSON contract.

### Changes

* `POST /chat` now supports `stream=true`
* Streaming emits SSE events:
  * `token`
  * `done`
  * `error`
* Streaming provider execution occurs outside the DB transaction
* Final persistence happens in a single DB transaction after provider completion
* Minimal demo UI added at `GET /ui`
* Streaming smoke test added

### Preserved invariants

* `/chat` remains the only write-path
* Non-stream mode preserves single-transaction semantics
* Streaming does not require schema changes
* Provider orchestration remains DB-agnostic
* Observability remains non-invasive


## Appendices

Detailed execution-level documentation, debugging playbooks, and deep technical references
are maintained in a separate companion document:

- **LLD Appendix — LLM Chat Platform (Debug & Deep Dive)**

This separation is intentional to keep the core LLD focused on architecture and decisions,
while allowing the appendix to evolve with operational learnings and real-world failures.


**This document reflects the state of the system up to Day 28.**
**Execution-level details and debugging notes are tracked in the Appendix.**
