# LLM Chat Platform — LLD (Low Level Design)

**Document type:** Living LLD + architectural decision log

**Scope:** Backend (FastAPI) for an LLM-based chat platform. This document captures low-level structure, implementation conventions, and the rationale behind key decisions.

**Source of truth:** This LLD is authoritative for decisions about runtime behavior, layering, configuration, and operational workflows.

---

## 1. Context and objectives

### 1.1 Problem statement

Build a backend foundation for an LLM chat platform that can evolve safely: predictable runtime behavior, clear module boundaries, reproducible operations (migrations), and strong traceability.

### 1.2 Current stack

* **FastAPI** (HTTP API)
* **PostgreSQL** (persistence)
* **Redis** (cache / future orchestration)
* **Docker Compose** (local/dev orchestration)

### 1.3 Guiding principles

* **Separation of concerns:** runtime API behavior vs operational workflows (migrations, readiness).
* **Explicit tradeoffs:** avoid hidden coupling and premature complexity.
* **Traceability:** changes are reflected in both code and documentation.
* **Incremental delivery:** foundations first (structure + discipline), features later.

---

## 2. Architecture overview

### 2.1 High-level components

1. **API (FastAPI)**

* Serves HTTP endpoints.
* Will orchestrate chat sessions, provider calls, and persistence over time.

2. **PostgreSQL**

* Stores structured data once models are introduced.
* Schema changes managed via Alembic migrations.

3. **Redis**

* Reserved for caching and future use cases (rate limiting, ephemeral state, background orchestration, queues).

### 2.2 Runtime coupling policy (critical)

**The API runtime must not be coupled to DB/Redis readiness at startup** in the current phase.

* No startup DB checks.
* No startup Redis checks.
* No automatic migration on startup.

Rationale:

* Deterministic API startup.
* Clear separation between operational steps and runtime availability.
* Avoid “dependency transient failure” preventing API boot.

---

## 3. Repository structure and module boundaries

### 3.1 Current structure (simplified)

```
app/
  main.py
  api/
    ops.py                 # operational endpoints
  core/
    settings.py            # configuration (pydantic-settings)
  infra/
    db.py                  # compatibility shim (re-export)
    db/
      base.py              # DeclarativeBase
      session.py           # async engine/session + helpers
    redis_client.py        # redis client init (if present)
  alembic/
    env.py
    versions/
  alembic.ini

README.md
LLD.md
.env.example
docker-compose.yml
Dockerfile
```

### 3.2 Layering rules

* **core/**

  * Configuration and cross-cutting primitives.
  * Must not depend on infra details.

* **infra/**

  * Infrastructure integration: DB engines/sessions, Redis client.
  * Can depend on `core.settings`.

* **api/**

  * HTTP boundary: request/response, operational endpoints.
  * Should not contain infra boot logic beyond dependency injection.

---

## 4. Configuration strategy

### 4.1 Source of truth

* Runtime configuration is derived from environment variables via `core.settings`.
* Alembic also resolves the DB URL from **`settings.database_url`**.

### 4.2 Database URL

* SQLAlchemy async URL format:

  * `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME`

* In Docker Compose, prefer using the **service name** as host:

  * `@postgres:5432/...`

Rationale:

* Service DNS is stable across Compose runs.
* Container names are not a stable interface.

---

## 5. Health and readiness

### 5.1 `/health` endpoint policy

* `GET /health` is **process-level only**.
* It validates only that the API process is running and responsive.

### 5.2 Dependency readiness policy

* Postgres and Redis are validated via Docker healthchecks:

  * Postgres: `pg_isready`
  * Redis: `redis-cli PING`

### 5.3 Deferred endpoint

* `/health/deps` (DB + Redis connectivity) is intentionally deferred to a later phase.

Rationale:

* Avoid early coupling and complexity.
* Introduce dependency checks once persistence usage is real and stable.

---

## 6. Database integration (SQLAlchemy 2.0 async)

### 6.1 Components

* `app/infra/db/base.py`

  * Defines `Base` via SQLAlchemy `DeclarativeBase`.

* `app/infra/db/session.py`

  * Defines async `engine`, `SessionLocal`, and `get_db()` dependency.
  * May include a `test_db_connection()` helper used for manual diagnostics.

* `app/infra/db.py` (shim)

  * Re-export module to avoid breaking imports while structure evolves.

### 6.2 Session management

* Use `async_sessionmaker`.
* `expire_on_commit=False` to avoid implicit lazy loads after commit in async contexts.

### 6.3 Startup behavior

* No mandatory DB connection checks on startup.
* DB connectivity is verified operationally or via Docker healthchecks.

---

## 7. Migrations (Alembic)

### 7.1 Decision

Alembic is enabled for **reproducible schema migrations**.

* Migrations are an **operational step**.
* Migrations are executed **inside the `api` container**.
* Alembic uses **SQLAlchemy async** migration flow.
* Alembic resolves DB URL from **`settings.database_url`**.

### 7.2 Layout

* `app/alembic/`
* `app/alembic.ini`

Rationale:

* Tooling lives next to application code.
* Avoids ambiguity across host vs container environments.

### 7.3 Alembic env.py requirements

* `target_metadata = Base.metadata`
* Async online migrations using:

  * `async_engine_from_config`
  * `asyncio.run(run_migrations_online())`
  * `connection.run_sync(...)`

### 7.4 Canonical commands

Run from project root:

```bash
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
docker compose exec -w /app/app api alembic revision -m "describe change"
docker compose exec -w /app/app api alembic downgrade -1
```

Validate applied version directly in Postgres:

```bash
docker compose exec postgres bash -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select * from alembic_version;"'
```

---

## 8. Redis integration

### 8.1 Current intent

Redis is included in the stack as a foundational dependency for:

* Caching
* Rate limiting
* Ephemeral session state
* Future background orchestration

### 8.2 Current runtime coupling

* No mandatory Redis checks on startup.
* Redis readiness validated via Docker healthcheck.

---

## 9. Logging and observability

### 9.1 Logging

* Use standard Python logging.
* Ensure logs are actionable (clear context, avoid noisy stack traces for expected transient issues).

### 9.2 Observability roadmap

Later phases may add:

* Structured logging (JSON)
* Request IDs / correlation IDs
* Metrics (Prometheus-compatible)
* Distributed tracing (OpenTelemetry)

---

## 10. Security and governance (baseline)

* Configuration via environment variables only; avoid secrets in repo.
* No runtime behavior should require elevated permissions.
* Migrations are operational and should be executed by trusted operators only.

---

## 11. Roadmap (implementation-level)

### 11.1 Next steps (near-term)

* Introduce the first real model(s) (e.g., conversation/session entities).
* Generate the first non-empty Alembic migration(s).
* Add `/health/deps` once persistence and caching are actively used.

### 11.2 Later

* LLM provider abstraction layer
* Conversation lifecycle + auditing
* Policy controls (rate limiting, quotas)
* LLMOps/LLMOps hooks:

  * prompt/version traceability
  * provider lifecycle
  * evaluation harness integration

---

## 12. Decision log (ADR-style, abbreviated)

### ADR-001 — Process-level `/health` only (current phase)

**Decision:** `/health` is process-level only. Dependency checks remain at Docker level.

**Why:** avoid early coupling; keep runtime deterministic.

**Impact:** operational health for DB/Redis is handled via container healthchecks; `/health/deps` deferred.

---

### ADR-002 — No startup coupling to DB/Redis

**Decision:** API does not check DB/Redis readiness on startup.

**Why:** resilience and predictable boot; avoid cascading failures.

**Impact:** operators rely on Docker health + operational commands for validation.

---

### ADR-003 — Alembic initialized under `app/` and executed in container

**Decision:** Alembic lives under `app/alembic*` and runs via `docker compose exec -w /app/app api alembic ...`.

**Why:** single canonical execution environment; reduces host/container drift.

**Impact:** migrations are reproducible across machines; docs provide canonical commands.

---

### ADR-004 — Alembic DB URL comes from `settings.database_url`

**Decision:** Alembic `env.py` sets `sqlalchemy.url` from `core.settings`.

**Why:** single source of truth; avoids brittle INI interpolation.

**Impact:** consistent configuration across runtime and tooling.

---
