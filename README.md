# LLM Chat Platform

Backend platform for building a **LLM-based chat system**, designed with strong architectural separation, explicit operational steps, and long-term evolvability in mind.

This repository intentionally prioritizes **clarity, traceability, and correctness** over premature feature density.

---

## Project goals

* Provide a clean backend foundation for LLM-powered chat applications
* Separate **runtime concerns** from **operational concerns** (DB readiness, migrations, etc.)
* Maintain an explicit and auditable evolution of the data model
* Serve as a reference-quality backend project (interview / portfolio grade)

---

## Tech stack

* **FastAPI** — HTTP API layer
* **PostgreSQL** — persistent storage
* **Redis** — caching / ephemeral data
* **SQLAlchemy 2.0 (async)** — ORM
* **Alembic** — schema migrations
* **Docker + Docker Compose** — reproducible environments

---

## Architectural principles

* **No DB or Redis checks at API startup**

  * `/health` is process-level only
  * Dependency readiness is handled by Docker healthchecks

* **Migrations are operational**

  * Alembic is never invoked automatically by the API
  * Schema changes are explicit, reproducible steps

* **Single source of truth for configuration**

  * `settings.database_url` is authoritative

---

## Repository structure (simplified)

```
app/
  main.py
  api/
    ops.py                  # operational endpoints (/health)
  models/
    __init__.py
    conversation.py
    message.py
  infra/
    db.py                   # compatibility shim (re-export)
    db/
      base.py               # DeclarativeBase
      session.py            # async engine/session + helpers
  alembic/
    env.py
    versions/
  alembic.ini
  requirements.txt

README.md
LLD.md
.env.example
Dockerfile
docker-compose.yml
```

---

## Health endpoint

The API exposes a **process-level** health endpoint:

```
GET /health
```

Characteristics:

* Confirms that the FastAPI process is alive
* Does **not** check Postgres or Redis
* Dependency readiness is validated via Docker Compose healthchecks

---

## Data model (Day 7 baseline)

### Conversation

Represents a logical chat session.

* `id` (UUID)
* `created_at`, `updated_at`
* optional `title`
* optional `metadata` (JSONB)

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

* `role = user` → human input
* `role = assistant` → model output
* `role = system` → system / control context

---

## Database migrations (Alembic)

Alembic is used for **reproducible schema evolution**.

### Key rules

* Migrations are never executed automatically at runtime
* Alembic always resolves the DB URL from `settings.database_url`
* Canonical execution environment is the `api` container

### Layout

```
app/alembic/
app/alembic.ini
```

### Canonical commands

All commands run inside the `api` container:

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
  * The repository’s migration graph

Typical failure symptoms:

* `Can't locate revision identified by ...`
* `KeyError` while resolving revisions

**Operational rule**

> Treat every Alembic revision file as a first-class source artifact.

---

## Development workflow (local)

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

## Documentation

* **README.md** — High-level overview and operational rules
* **LLD.md** — Living low-level design and architectural decisions

---

## Status

* Day 1–5: Infrastructure, Docker, DB scaffolding
* Day 6: Alembic initialization and migration pipeline
* Day 7: Conversation & Message persistence baseline

Next steps will build on this stable core (repositories, API endpoints, LLM adapters).
