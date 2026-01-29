# LLM Chat Platform

Backend platform for building a **LLM-based chat system**, designed with strong architectural separation, explicit operational steps, and long-term evolvability in mind.

This repository intentionally prioritizes **clarity, traceability, and correctness** over premature feature density.

> This project focuses on the **operational side of AI systems (LLMOps)**: running LLM-powered workloads with transactional guarantees, observability, traceability, and production-safe failure handling.
> Model quality and prompt engineering are intentionally out of scope.

---

## Project goals

* Provide a clean backend foundation for LLM-powered chat applications
* Separate **runtime concerns** from **operational concerns** (DB readiness, migrations, telemetry)
* Maintain an explicit and auditable evolution of the data model
* Serve as a reference-quality backend project (interview / portfolio grade)

---

## Design philosophy

This platform is designed around the assumption that **LLM calls are external, fallible, and expensive operations**.

As a result, the system explicitly prioritizes:

* Clear transaction boundaries
* Deterministic persistence semantics
* Non-invasive observability and telemetry
* Operational correctness over feature velocity

---

## Tech stack

* **FastAPI** — async HTTP API
* **PostgreSQL** — persistent storage
* **Redis** — caching / ephemeral data
* **SQLAlchemy 2.0 (async)** — ORM
* **Alembic** — schema migrations
* **Docker + Docker Compose** — reproducible environments

---

## Architectural principles

### Runtime vs Operations

* **No DB or Redis checks at API startup**

  * `/health` is process-level only
  * Dependency readiness is handled via Docker healthchecks

* **Migrations are operational concerns**

  * Alembic is never executed automatically by the API
  * Schema changes are explicit, reproducible steps

* **Single source of truth for configuration**

  * `settings.database_url` is authoritative

---

## Repository structure (simplified)

```
app/
  main.py
  api/
    routes/
      chat.py               # /chat endpoint (write-path)
      usage_events.py       # usage and inspection endpoints (read-path)
    ops.py                  # /health
  models/
    conversation.py
    message.py
    usage_event.py
  infra/
    db/
      base.py               # DeclarativeBase
      session.py            # async engine/session
    schemas/
      trace.py              # trace reconstruction schemas
      usage_events.py
  services/
    trace.py                # deterministic trace reconstruction

alembic/
  env.py
  versions/

scripts/
  dev_up.py
  dev_down.py
  trace_request.py

README.md
docs/
  lld_llm_chat_platform_live_doc.md
  lld_apendix.md
.env.example
Dockerfile
docker-compose.yml
docker-compose.dev.yml
```

---

## Health endpoint

```
GET /health
```

Characteristics:

* Confirms FastAPI process is alive
* Does **not** check Postgres or Redis
* Dependency readiness validated by Docker Compose healthchecks

---

## Data model (baseline)

### Conversation

Represents a logical chat session.

* `id` (UUID)
* `created_at`, `updated_at`
* optional `title`
* optional `metadata` (JSONB)

---

### Message

Represents a single message within a conversation.

* `id` (UUID)
* `conversation_id` (FK → Conversation)
* `role`: `user | assistant | system`
* `content`
* `created_at`

**Index**

* `(conversation_id, created_at)` — optimized for ordered retrieval

**Semantic contract**

* `user` → human input
* `assistant` → model output
* `system` → control / orchestration context

---

### UsageEvent (LLMOps — minimal)

Represents a single usage / telemetry event related to a model invocation.

Tracked fields include:

* `provider`
* `model_version`
* `prompt_version`
* `request_id`
* `conversation_id` (FK, nullable)
* `message_id` (FK, nullable)
* `latency_ms`
* token counts (when available)
* `status`
* `error_message`
* `created_at`

This table is the **foundation for observability, cost analysis, and auditability**.

---

## `/chat` endpoint — transactional write-path

The `/chat` endpoint implements a **fully transactional write-path**.

Each request executes, within a single database transaction:

1. Create or validate `Conversation`
2. Persist `Message (user)`
3. Execute model logic (currently a stub)
4. Persist `Message (assistant)`
5. Persist `UsageEvent` with valid foreign keys

On failure:

* The transaction is rolled back
* A best-effort `UsageEvent` with `status=error` is recorded **without foreign keys**

This guarantees atomicity while preserving **post-hoc traceability under failure conditions**.

---

## End-to-end traceability (Day 10)

Every chat execution can be deterministically reconstructed using a `request_id`, **without modifying the write-path or database schema**.

This enables:

* Post-hoc auditing and inspection
* Deterministic input/output reconstruction
* Latency and cost analysis
* Failure investigation without partial persistence

Trace reconstruction is implemented as a **read-only analysis layer** and documented in detail in the LLD appendix.

---

## Database migrations (Alembic)

Alembic is used for **explicit, reproducible schema evolution**.

### Key rules

* Migrations are never executed automatically at runtime
* Alembic always resolves the DB URL from `settings.database_url`
* Canonical execution environment is the `api` container

### Canonical commands

```bash
docker compose exec -w /app/app api alembic current
```

```bash
docker compose exec -w /app/app api alembic upgrade head
```

```bash
docker compose exec -w /app/app api alembic revision --autogenerate -m "describe change"
```

---

## ⚠️ Migration integrity rule (critical)

The API image is built using:

```
COPY app /app/app
```

This means:

* **All files under `app/alembic/versions/` must be committed to Git**
* Rebuilding the image without committed revisions can desynchronize:

  * Postgres `alembic_version`
  * Repository migration graph

Typical failure symptoms:

* `Can't locate revision identified by ...`
* `KeyError` while resolving revisions

> Treat every Alembic revision file as a first-class source artifact.

---

## Development workflow

### Standard (immutable images)

```bash
git clone <repo>
cd llm-chat-platform
cp .env.example .env
docker compose up -d
```

Verify:

* `/health` responds
* Postgres and Redis containers are healthy

---

### Development mode (DEV — bind mounts)

Local development uses **bind mounts** to avoid rebuilding images when:

* modifying Alembic migrations
* iterating on ORM models
* debugging import paths

Start DEV environment:

```bash
./scripts/dev_up.py
```

Equivalent to:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  up -d
```

> ⚠️ DEV only. Production keeps images immutable.

---

## Project status

Current state: **Day 10**

The platform provides:

* A stable, transactional write-path for chat interactions
* A read-only inspection and auditing layer
* Deterministic end-to-end traceability via `request_id`

### Implemented

* Atomic chat write-path (`POST /chat`)
* Conversation and message persistence
* UsageEvent-based telemetry
* End-to-end execution trace reconstruction

### Roadmap

**Near-term (Day 11)**

Provider abstraction (no vendor lock-in):

- `ProviderPort` (async-first) with explicit contract:
  - `ProviderInput` (request_id + messages, provider-agnostic)
  - `ProviderResult` (content + minimal metadata + metrics)
- Deterministic `StubProvider`:
  - configurable simulated latency
  - deterministic failure mode for error-path validation
  - no external IO / no side effects
- DB-agnostic orchestration layer:
  - `ChatService` orchestrates input → provider → output
  - no DB access, no transactions, no HTTP semantics

**Near-term (Day 12)**

ChatService integration into write-path (`/chat`):

- `/chat` endpoint delegates model execution to `ChatService`
  - preserves atomic write-path semantics (single DB transaction)
  - preserves flush ordering (IDs before FKs)

- UsageEvent emission aligned with LLMOps minimum viable:
  - success path: full metadata + valid foreign keys
  - error path: best-effort telemetry without FKs (never blocks response)

- Provider mode controlled via environment (`STUB_PROVIDER_MODE`)
  - enables deterministic success and failure scenarios

- Reproducible smoke evidence:
  - success path runner (message persistence + usage_event success)
  - error path runner (rollback + usage_event error)

- Regression gates:
  - contract tests passing (core remains DB-agnostic)
  - OpenAPI and read-paths unchanged


Evidence / reproducibility:

- Container-run runners (under `app/scripts/`):
  - `run_stub_chat.py` (ok path + error path)
  - `run_stub_determinism.py` (determinism + sensitivity checks)
- Contract tests (pure, no DB):
  - `app/tests/core/test_stub_provider_contract.py`
  - `app/tests/core/test_chat_service_contract.py`

> Note: `/chat` integration is intentionally deferred until the provider contract is validated.

**Future**

* Streaming responses
* Authentication, rate limiting, quotas
* Aggregated metrics and dashboards

---

## Documentation

* **README.md** — operational overview and invariants
* **docs/lld_llm_chat_platform_live_doc.md** — living low-level design
* **docs/lld_apendix.md** — deep technical appendices and traceability details
