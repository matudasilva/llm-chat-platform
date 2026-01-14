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
    ops.py                  # /health
    chat.py                 # /chat endpoint
  models/
    conversation.py
    message.py
    usage_event.py
  infra/
    db.py                   # compatibility shim
    db/
      base.py               # DeclarativeBase
      session.py            # async engine/session
  services/
    usage_logger.py         # telemetry logging
  alembic/
    env.py
    versions/
  alembic.ini

scripts/
  dev_up.py

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
* `latency_ms`
* token counts (when available)
* `status`
* `error_message`
* `created_at`

This table is the **foundation for observability, cost analysis and auditability**.

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

## `/chat` endpoint – current state

* Functional
* Measures request latency
* Persists `usage_events`
* Uses a **stub provider** (no external LLM dependency yet)

Acts as a **stable integration point** for future LLM providers.

---

## Project status (stable checkpoint)

This repository is currently in a **stable and consistent state**, closing the structural phase:

* Alembic migrations aligned (single head)
* Core models implemented:

  * `Conversation`
  * `Message`
  * `UsageEvent`
* Minimal telemetry integrated
* Fast iteration DEV environment in place

All future work builds on this base.

---

## Next steps (not implemented yet)

* LLM provider integration (OpenAI / Bedrock / etc.)
* Conversation → message → usage chaining
* Background / async-safe usage logging
* Aggregated metrics and dashboards
* Auth, rate limiting, quotas

---

## Documentation

* **README.md** — Operational overview and rules
* **LLD.md** — Living low-level design and architectural decisions
