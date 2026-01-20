# Low Level Design (LLD)

## LLM Chat Platform

**Status:** Stable baseline — validated up to Day 9

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

  * Conversation create/validate
  * Persist user + assistant messages
  * Persist usage event in the same transaction
* Error handling hardened (rollback + error telemetry without FKs)
* Router/import path issues resolved (single authoritative chat router)

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

### 15.5 Stub provider semantics

* Deterministic response: `"stub: provider not configured yet"`
* No external LLM calls
* No token accounting

The stub exists to validate the persistence + telemetry pipeline before provider integration.

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

---

## Appendices

Detailed execution-level documentation, debugging playbooks, and deep technical references
are maintained in a separate companion document:

- **LLD Appendix — LLM Chat Platform (Debug & Deep Dive)**

This separation is intentional to keep the core LLD focused on architecture and decisions,
while allowing the appendix to evolve with operational learnings and real-world failures.


**End of document — valid up to Day 9**
