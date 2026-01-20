# LLM Chat Platform

Backend platform for building a **LLM-based chat system**, designed with strong architectural separation, explicit operational steps, and long-term evolvability in mind.

This repository intentionally prioritizes **clarity, traceability, and correctness** over premature feature density.

---

## Project goals

* Provide a clean backend foundation for LLM-powered chat applications
* Separate **runtime concerns** from **operational concerns** (DB readiness, migrations, telemetry)
* Maintain an explicit and auditable evolution of the data model
* Serve as a reference-quality backend project (interview / portfolio grade)

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

* **Migrations are operational**

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
    ops.py                  # /health
  models/
    conversation.py
    message.py
    usage_event.py
  infra/
    db/
      base.py               # DeclarativeBase
      session.py            # async engine/session
  services/
    usage_logger.py         # telemetry helper (legacy / optional)

alembic/
  env.py
  versions/

scripts/
  dev_up.py
  dev_down.py

README.md
LLD.md
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
* `system` → control / system context

---

### UsageEvent (LLMOps – minimal)

Represents a single usage / telemetry event related to a model invocation.

Tracked fields include:

* `provider`
* `model_version`
* `prompt_version`
* `request_id`
* `conversation_id` (FK)
* `message_id` (FK)
* `latency_ms`
* token counts (when available)
* `status`
* `error_message`
* `created_at`

This table is the **foundation for observability, cost analysis and auditability**.

---

## `/chat` endpoint — current state (Day 9)

The `/chat` endpoint implements a **fully transactional write-path**.

Each request executes, within a single DB transaction:

1. Create or validate `Conversation`
2. Persist `Message (user)`
3. Execute model logic (currently a stub)
4. Persist `Message (assistant)`
5. Persist `UsageEvent` with valid foreign keys

On failure:

* Transaction is rolled back
* A best-effort `UsageEvent` with `status=error` is recorded **without FKs**

This guarantees **atomicity and traceability**.

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

### Development mode (DEV – bind mounts)

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

## Project status (stable checkpoint)

This repository is currently in a **stable and consistent state**, closing the structural phase:

* Alembic migrations aligned (single head)
* Core models implemented:

  * `Conversation`
  * `Message`
  * `UsageEvent`
* `/chat` endpoint fully transactional
* Conversation, messages and usage events persisted atomically
* Foreign key integrity enforced on success paths
* Error paths explicitly avoid FK coupling to prevent cascade failures
* Minimal telemetry integrated and validated against the database
* Fast iteration DEV environment in place

This checkpoint reflects the **Day N update**, where the chat write-path, transaction boundaries, and telemetry semantics were finalized and verified end-to-end.

All future work builds on this base.

---

## Next steps (not implemented yet)

* Real LLM provider integration (OpenAI / Bedrock / etc.)
* Service layer extraction (`ChatService`)
* Streaming responses
* Aggregated metrics and dashboards
* Auth, rate limiting, quotas

---

## Documentation

* **README.md** — operational overview and invariants
* **LLD.md** — living low-level design and architectural decisions
