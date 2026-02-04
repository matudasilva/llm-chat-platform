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

## Non-goals (explicit)

This project intentionally does **not** aim to:

* optimize prompt quality or model output
* benchmark LLM vendors
* provide UI / frontend components
* act as a full SaaS product

The focus is strictly on **running LLM workloads safely and correctly in production-like environments**.

---

## Intended audience

This repository is designed for:

* Backend / Platform Engineers
* Cloud & LLMOps Architects
* Engineers preparing for senior technical interviews
* Teams learning how to operationalize LLM workloads safely

---

## Tech stack

* **FastAPI** — async HTTP API
* **PostgreSQL** — persistent storage
* **Redis** — caching / ephemeral data (reserved)
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

  * `settings.database_url` is authoritative for both runtime and Alembic

---

## Repository structure (simplified)

```
app/
  main.py
  api/
    routes/
      chat.py               # /chat endpoint (write-path)
      usage_events.py       # usage & inspection endpoints (read-path)
    ops.py                  # /health
  core/
    domain/                 # provider contracts, ChatService, errors
  models/
    conversation.py
    message.py
    usage_event.py
  infra/
    db/
      base.py
      session.py
  services/
    trace.py                # deterministic trace reconstruction

alembic/
  env.py
  versions/

scripts/
  dev_up.py
  dev_down.py
  run_stub_chat.py
  run_stub_determinism.py

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

---

### UsageEvent (LLMOps — minimal)

Represents a telemetry event related to a model invocation.

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
3. Execute model logic via `ChatService`
4. Persist `Message (assistant)`
5. Persist `UsageEvent` with valid foreign keys

### Failure semantics

On failure:

* The transaction is rolled back
* A best-effort `UsageEvent` with `status=error` is recorded **without foreign keys**

This guarantees atomicity while preserving **post-hoc traceability under failure conditions**.

---

## Provider abstraction & orchestration

### ProviderPort

Providers implement a single async-first contract:

```
ProviderPort.generate(input: ProviderInput) -> ProviderResult
```

* Provider contracts are **DB-agnostic**
* No HTTP or FastAPI semantics
* No persistence side effects

### ChatService

`ChatService` is a pure orchestration layer:

* Accepts domain messages
* Invokes the provider with timeout protection
* Returns assistant output + provider metadata

Non-responsibilities:

* No database access
* No transaction management
* No HTTP concerns

---

## End-to-end traceability

Every execution can be deterministically reconstructed using a `request_id`, **without modifying the write-path or schema**.

Capabilities:

* Input/output reconstruction
* Latency and cost inspection
* Failure investigation
* Auditable execution history

Trace reconstruction is implemented as a **read-only analysis layer** and documented in the LLD Appendix.

---

## Database migrations (Alembic)

Alembic is used for **explicit, reproducible schema evolution**.

### Key rules

* Migrations are never executed automatically at runtime
* Alembic resolves DB URL from `settings.database_url`
* Canonical execution environment is the `api` container

### Canonical commands

```bash
docker compose exec -w /app/app api alembic current
```

```bash
docker compose exec -w /app/app api alembic upgrade head
```

---

## ⚠️ Migration integrity rule (critical)

The API image is built using:

```
COPY app /app/app
```

This implies:

* **All Alembic revision files must be committed**
* Missing revisions will desynchronize the migration graph

Typical symptoms:

* `Can't locate revision identified by ...`
* `KeyError` during Alembic resolution

---

## Development workflow

### Standard

```bash
git clone <repo>
cd llm-chat-platform
cp .env.example .env
docker compose up -d
```

### Development mode (bind mounts)

```bash
./scripts/dev_up.py
```

Used for:

* Alembic iteration
* ORM changes
* import/debug cycles

---

## Test & evidence

### Contract tests (DB-agnostic)

```bash
PYTHONPATH=app pytest -q
```

### Deterministic runners

```bash
PYTHONPATH=app python app/scripts/run_stub_chat.py
```

```bash
PYTHONPATH=app python app/scripts/run_stub_determinism.py
```

---

## Project status

## Project status

**Current state: Day 13 — Hardened & validated**


### Day 13 — Hardening & Guardrails

This iteration focuses on **operational hardening**, not feature expansion.

The goal of Day 13 is to ensure that the `/chat` write-path behaves
**correctly under adverse conditions**, including invalid input,
provider failures, and telemetry issues.

Guarantees added in Day 13:

* Explicit input guardrails:
  * blank or whitespace-only messages are rejected
  * oversized messages are rejected deterministically
* Request payload size bounded via middleware
* Provider execution is hardened:
  * explicit timeout handling
  * provider failures normalized into domain-level errors
* Error handling is controlled:
  * no raw provider exceptions leak through the API
  * transactional integrity is preserved on failure
* Telemetry is defensive:
  * UsageEvent emission is best-effort
  * telemetry failures never break the request flow
* Contract and guardrail tests act as regression gates

No changes were introduced to:

* database schema
* Alembic migrations
* API surface
* transactional semantics of `/chat`


### Implemented (as of Day 13)

* Transactional `/chat` write-path
* Provider abstraction + orchestration layer
* Deterministic stub provider
* End-to-end traceability
* Regression-safe integration


## Day 14 — Operational Hardening & Evidence

- Internal provider diagnostics
  - Provider timeout and execution failures are logged with full exception context
  - Client-facing errors remain sanitized

- Telemetry best-effort guarantee
  - `UsageEvent` failures never break `/chat` (covered by explicit test)

- Request payload size guard
  - Requests exceeding `MAX_REQUEST_BYTES` return HTTP 413
  - Verified via `tests/api/test_request_size_limit.py`

- Defensive metrics
  - latency and token counters are clamped to non-negative values before persistence


---

## Documentation

* **README.md** — operational overview and invariants
* **docs/lld_llm_chat_platform_live_doc.md** — living low-level design
* **docs/lld_apendix.md** — deep technical appendices and traceability details

---

## Recommendations for next iterations

* Add streaming support without breaking atomicity
* Introduce real providers (OpenAI / Bedrock) via adapters
* Add auth, quotas, and rate limiting
* Aggregate usage metrics and dashboards

---

**This repository is intentionally built as a correctness-first reference system.**
