# LLM Chat Platform

Backend project in **FastAPI** oriented to an **LLM-based chat platform**. This repository is intentionally built as a portfolio-grade foundation: clean layering, explicit architectural decisions, and documentation-first evolution.

**Current stack (Docker Compose):**

* **FastAPI** (API runtime)
* **PostgreSQL** (relational persistence)
* **Redis** (cache / future orchestration)

This README acts as a light **HLD** (High Level Design). The detailed, living design and decision log lives in **LLD.md**.

---

## Goals

* Provide a clean, extensible backend baseline for a chat platform that can integrate multiple LLM providers.
* Maintain strong fundamentals: configuration hygiene, operational ergonomics, traceability, and predictable behavior.
* Keep early phases intentionally “simple but correct” (avoid premature coupling and complexity).

---

## Current status

### Implemented

* Dockerized stack: **api + postgres + redis**
* Process-level health endpoint: `GET /health`
* SQLAlchemy 2.0 **async** scaffolding:

  * `app/infra/db/base.py` (DeclarativeBase)
  * `app/infra/db/session.py` (async engine/session + helpers)
  * `app/infra/db.py` (shim / re-export)
* Dependency healthchecks handled at **Docker level**:

  * Postgres: `pg_isready`
  * Redis: `redis-cli PING`
* Alembic initialized for reproducible migrations (pipeline/tooling; no runtime coupling)

### Explicit non-goals (current phase)

* No DB/Redis checks in API startup.
* No dependency-level health endpoint yet (e.g., `/health/deps`).
* No models beyond scaffolding unless introduced explicitly in the roadmap.

These are deliberate decisions to keep the API runtime resilient and predictable in early phases.

---

## Architecture snapshot

* **API (FastAPI)** exposes HTTP endpoints and will evolve to orchestrate chat sessions, provider calls, and persistence.
* **PostgreSQL** will store conversation state and operational metadata once models are introduced.
* **Redis** is reserved for caching and future use cases (rate limiting, ephemeral session state, background orchestration, queues, etc.).

---

## Repository structure (simplified)

> Paths reflect the intended current layout. The authoritative, evolving view is in **LLD.md**.

```
app/
  main.py
  api/
    ops.py                 # operational endpoints (e.g., /health)
  infra/
    db.py                  # compatibility shim (re-export)
    db/
      base.py              # DeclarativeBase
      session.py           # async engine/session + helpers
  alembic/                 # migrations (Alembic)
  alembic.ini              # Alembic config (kept under app/)
  requirements.txt

README.md
LLD.md
.env.example
Dockerfile
docker-compose.yml
```

---

## Prerequisites

* Docker + Docker Compose

(You can run everything in containers; installing Python locally is optional.)

---

## Configuration

Copy the example env file and adjust values as needed:

```bash
cp .env.example .env
```

The full configuration contract lives in `.env.example`. At minimum you should expect:

* `APP_ENV` (e.g., `development`)
* `LOG_LEVEL` (e.g., `INFO`)
* `DATABASE_URL` (SQLAlchemy async URL)

Example `DATABASE_URL`:

```
postgresql+asyncpg://llmchat:__REDACTED__@postgres:5432/llmchat
```

---

## Run the stack

Build and start:

```bash
docker compose up --build
```

Check container status:

```bash
docker compose ps
```

---

## Health

### API health (process-level)

`/health` is intentionally **process-level only** (no DB/Redis connectivity checks).

Default local URL (depending on your `docker-compose.yml` ports mapping):

```bash
curl -s http://127.0.0.1:8001/health
```

Expected:

```json
{"status":"ok","app_env":"development"}
```

### Dependency health (Docker-level)

Postgres and Redis readiness are validated at the Docker level via container healthchecks:

* Postgres: `pg_isready`
* Redis: `redis-cli PING`

Inspect health state:

```bash
docker compose ps
```

---

## Database access (manual)

Open a `psql` session inside the Postgres container:

```bash
docker compose exec postgres bash -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

---

## Database migrations (Alembic)

Alembic is used for **reproducible schema migrations**.

### Design rules

* Migrations are an **operational step** and are **not** executed on API startup.
* Alembic resolves the DB URL from `settings.database_url` (single source of truth).
* Canonical execution environment is inside the `api` container.

### Layout

* `app/alembic/`
* `app/alembic.ini`

### Canonical commands (Docker)

All commands below run inside the `api` container, with working directory set to `/app/app`:

Current revision:

```bash
docker compose exec -w /app/app api alembic current
```

Upgrade to latest:

```bash
docker compose exec -w /app/app api alembic upgrade head
```

Create a new revision:

```bash
docker compose exec -w /app/app api alembic revision -m "describe change"
```

Rollback one revision:

```bash
docker compose exec -w /app/app api alembic downgrade -1
```

Validate applied revision directly in Postgres:

```bash
docker compose exec postgres bash -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select * from alembic_version;"'
```

---

## Operational notes

### Why no startup DB checks?

This is a deliberate resilience and ergonomics choice during early phases:

* Deterministic API startup in containerized environments.
* Clear separation between runtime behavior and operational workflows (migrations/readiness).
* Avoid making the API unavailable just because a dependency is temporarily unavailable at boot time.

Dependency-level checks and `/health/deps` will be introduced later once persistence is mature.

---

## Roadmap (high-level)

### Near-term

* Introduce first persistence models and the first non-empty migration(s)
* Add `GET /health/deps` (DB + Redis connectivity) as a separate endpoint
* Expand observability foundations once core workflow exists

### Later

* LLM provider integration layer (cloud + on-prem)
* Conversation lifecycle, auditing, and policy controls
* LLMOps concerns: provider lifecycle, governance, prompt/version traceability, evaluation hooks

---

## Documentation

* **LLD.md**: living low-level design and architectural decision log
