# LLM Chat Platform

## Low-Level Design (LLD)

**Document type:** Living Low-Level Design + Architectural Decision Record (ADR) log
**Scope:** Backend (FastAPI)
**Audience:** Backend architects, maintainers, operators
**Status:** Stable checkpoint — **Day 8**

---

## 0. Document intent

This LLD describes **how the system works internally** and the **operational rules** required to keep it reproducible.

* README = high-level entry point and day-to-day usage
* LLD = **normative** technical design + ADRs + operational invariants

Changes that affect architecture, data model, or operational posture must be recorded as:

* a new ADR section (preferred), or
* an explicit update under the relevant section

---

## 1. System overview

LLM Chat Platform is a backend designed to support **LLM-driven chat interactions**, prioritizing:

* architectural order
* operational traceability
* reproducible persistence
* safe evolution through versioned schema changes

The platform is intentionally built around explicit boundaries:

* deterministic API startup (no dependency checks at runtime)
* strict separation between runtime and operational workflows
* migration discipline (repository is the schema source of truth)
* minimal, best-effort telemetry foundation (LLMOps baseline)

---

## 2. Architectural principles

### 2.1 Runtime vs operations separation

The API runtime does **not** execute operational logic:

* does not validate external dependencies on startup
* does not run migrations
* does not attempt to “self-heal” the environment

Operations are **explicit** and performed by operators / CI / runbooks:

* migrations
* deep readiness checks
* stamping / repair procedures

---

### 2.2 Deterministic startup

The API process must start regardless of:

* PostgreSQL availability
* Redis availability

Transient dependency failures must not prevent the HTTP process from coming up.

---

### 2.3 Single source of truth for configuration

* All configuration flows through `core.settings`
* `settings.database_url` is the authoritative DB URL
* No duplication of connection strings across code, Alembic, or Docker

---

### 2.4 Reproducible persistence

* The schema state is defined by **versioned migrations**
* The database is **not** the source of truth
* The repository is the source of truth

---

### 2.5 Incremental design

Do not introduce layers and abstractions without stable need.

The platform evolves by:

* adding small, testable increments
* preserving traceability
* avoiding premature framework complexity

---

## 3. Logical architecture

### 3.1 Components

1. **API (FastAPI)**

   * HTTP boundary
   * orchestrates conversation and message workflows
   * records minimal usage telemetry
   * does not perform infra bootstrap

2. **PostgreSQL**

   * durable persistence
   * schema managed exclusively through Alembic

3. **Redis**

   * prepared for caching / rate limiting / ephemeral state
   * not actively used in the current checkpoint

---

## 4. Repository structure and layering

### 4.1 Structure (simplified)

```
app/
  main.py

  api/routes/
    ops.py                  # /health
    chat.py                 # /chat endpoint

  core/
    settings.py

  infra/
    db.py                   # compatibility shim (re-export)
    db/
      base.py               # DeclarativeBase
      session.py            # async engine/session + get_db()
    redis_client.py

  models/
    conversation.py
    message.py
    usage_event.py

  services/
    usage_logger.py         # best-effort telemetry logger

  alembic/
    env.py
    versions/

  alembic.ini

scripts/
  dev_up.py
  dev_down.py

README.md
lld_llm_chat_platform_live_doc.md
.env.example
Dockerfile
docker-compose.yml
docker-compose.dev.yml
```

### 4.2 Layering rules

* `core/` must not depend on `infra/`
* `infra/` may depend on `core.settings`
* `api/` does not execute infra bootstrap logic
* `models/` define domain structure (data), not orchestration behavior

---

## 5. Configuration

### 5.1 Strategy

* environment variables → `core.settings`
* prohibited:

  * hardcoding connection values
  * duplicating URLs
  * fragile string interpolation across layers

### 5.2 Database URL

Required format:

```
postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
```

In Docker Compose:

* `HOST` must be the service name (`postgres`)

`settings.database_url` remains the single source of truth.

---

## 6. Health and readiness

### 6.1 `/health`

* **process-level** endpoint
* validates only that the API process responds
* does not check Postgres or Redis

### 6.2 Dependency readiness

Validated via Docker healthchecks:

* PostgreSQL → `pg_isready`
* Redis → `redis-cli PING`

The API does not implement readiness logic.

---

## 7. Data access (SQLAlchemy 2.0 async)

### 7.1 Core building blocks

* `infra/db/base.py` → `DeclarativeBase`
* `infra/db/session.py` → async engine, sessionmaker, `get_db()`
* `infra/db.py` → compatibility shim

### 7.2 Rules

* `expire_on_commit=False`
* no mandatory checks at startup
* DB sessions are explicit dependencies

---

## 8. Migrations (Alembic)

### 8.1 Nature

* migrations are operational
* never automatic
* never executed by the API runtime

### 8.2 Canonical execution

```
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
docker compose exec -w /app/app api alembic revision -m "message"
docker compose exec -w /app/app api alembic downgrade -1
```

### 8.3 Configuration

* DB URL resolved from `settings.database_url`
* async migration pattern
* `target_metadata = Base.metadata`

### 8.4 Operational invariant (critical)

The API image build uses:

```
COPY app /app/app
```

Therefore:

* **every file in `app/alembic/versions/` must be committed**
* rebuilding without committed revisions can desynchronize:

  * Postgres `alembic_version`
  * repository revision graph

Typical symptoms:

* `Can't locate revision identified by ...`
* `KeyError` while resolving revisions
* multiple heads

---

## 9. Domain models

### 9.1 Conversation

**Table:** `conversations`

* `id` (UUID, PK)
* `created_at` (timestamptz)
* `updated_at` (timestamptz)
* `title` (nullable)
* `metadata` (JSONB, nullable)

---

### 9.2 Message

**Table:** `messages`

* `id` (UUID, PK)
* `conversation_id` (FK, ON DELETE CASCADE)
* `role` (`user | assistant | system`)
* `content`
* `created_at`

**Index:** `(conversation_id, created_at)`

**Semantic contract**

* `user` → human input
* `assistant` → model output
* `system` → system/control context

---

### 9.3 UsageEvent (Telemetry / LLMOps baseline)

**Objective**: capture minimal request-level telemetry even before a real provider exists.

**Table:** `usage_events`

Main fields:

* `id` (UUID PK)
* `conversation_id` (FK nullable → `conversations.id`, ON DELETE SET NULL)
* `message_id` (FK nullable → `messages.id`, ON DELETE SET NULL)
* `provider` (varchar 64)
* `model_version` (varchar 128)
* `prompt_version` (varchar 64)
* `request_id` (UUID, nullable)
* `input_tokens` (int, nullable)
* `output_tokens` (int, nullable)
* `total_tokens` (int, nullable)
* `latency_ms` (int, nullable)
* `status` (varchar 32, nullable)
* `error_message` (text, nullable)
* `timestamp` (timestamptz, default now)

Indexes:

* `ix_usage_events_request_id (request_id)`
* `ix_usage_events_conversation_ts (conversation_id, timestamp)`
* `ix_usage_events_message_id (message_id)`

SQL verification:

```sql
select provider,
       model_version,
       prompt_version,
       status,
       latency_ms,
       total_tokens,
       timestamp
from usage_events
order by timestamp desc
limit 5;
```

---

## 10. Dev / Prod split (Day 8)

### 10.1 Objective

Separate the **development flow** (fast, iterative) from the **production build flow** (immutable and reproducible).

### 10.2 Technical decision

**Production / base** (`docker-compose.yml`)

* immutable image build using `COPY app /app/app`

**Development overlay** (`docker-compose.dev.yml`)

* bind mount the code to avoid rebuilds
* propagate UID/GID to avoid root-owned artifacts

```yaml
services:
  api:
    user: "${LOCAL_UID:-1000}:${LOCAL_GID:-1000}"
    volumes:
      - ./app:/app/app
    environment:
      APP_ENV: dev
```

### 10.3 Rationale

* prevents losing generated artifacts at rebuild time
* accelerates iteration on migrations, models, and endpoints
* preserves strict immutability for production

### 10.4 Trade-offs

* dev bind mounts do not perfectly replicate production runtime
* mitigation: dev overlay is strictly dev-only; prod remains immutable

---

## 11. Migration stabilization (Day 8)

### 11.1 Observed problem

Databases were observed in a state where they were stamped with revisions missing from the repository/image, causing:

* `Can't locate revision identified by ...`
* multiple heads
* `DuplicateTableError` / already-existing objects

### 11.2 Decision and solution

* reconstructed the revision chain with **noop / preserve-chain** migrations where necessary
* resolved multiple heads using explicit **merge** revisions
* preserved historical no-op revisions for traceability

### 11.3 Current revision chain (conceptual)

* baseline init (noop)
* descriptive change (noop) as branchpoint
* preserve-chain branch (noop)
* real migration: conversations/messages
* mergepoint between heads
* additional preservation for intermediate stamped revisions
* creation/stabilization of usage_events

### 11.4 Verification commands

```bash
docker compose exec -T -w /app/app api alembic current
```

```bash
docker compose exec -T -w /app/app api alembic heads
```

```bash
docker compose exec -T -w /app/app api alembic history --verbose | tail -n 60
```

Acceptance criteria:

* `current == heads`
* a single operational head exists

---

## 12. Telemetry logging service (best-effort)

### 12.1 Objective

Log telemetry without breaking the endpoint, even if:

* the DB is unavailable
* insert/commit fails

### 12.2 Conceptual interface

`log_usage_event(...)`:

* creates a `UsageEvent`
* commits
* swallows and logs errors so request flow remains intact

### 12.3 Endpoint integration pattern

* endpoint records telemetry in a `finally` block
* failures in telemetry logging must not affect user response

---

## 13. API `/chat` stub + telemetry (Day 8)

### 13.1 Current behavior

* returns a stub response (no real provider yet)
* measures latency via `time.perf_counter`
* generates `request_id`
* logs a `usage_event` in `finally`

### 13.2 Why it exists now

* validates DB integration and commit semantics
* validates table + indexes
* prepares token integration when a provider is added

---

## 14. Development scripts

### 14.1 Objective

Avoid repeating long compose override commands and standardize the dev workflow.

### 14.2 Scripts

* `scripts/dev_up.py` — starts dev environment with overlay
* `scripts/dev_down.py` — stops dev environment

Canonical usage:

```bash
./scripts/dev_up.py
```

---

## 15. Operational lessons learned (Runbook material)

### 15.1 Golden rule

In **immutable image mode** (no bind mounts), any file generated inside the container
(e.g., `alembic merge`) must be committed on the host or it will be lost at rebuild.

### 15.2 Recommended practice

* Dev: bind mounts + UID/GID propagation
* Prod: immutable, reproducible image builds

---

## 16. Definition of Done (Day 8 checkpoint)

* Alembic

  * `alembic current == alembic heads`
  * migrations reproducible on a fresh environment

* Database

  * tables `conversations`, `messages`, `usage_events` present

* Application

  * `/chat` responds
  * inserts rows into `usage_events`

* DevEx

  * `docker-compose.dev.yml` present and documented
  * `scripts/dev_up.py` present and usable

---

## 17. Architectural Decision Records (ADRs)

### ADR-001 — No DB/Redis checks at startup

**Decision:** the API does not validate dependencies during startup.
**Rationale:** deterministic startup; operational workflows own readiness.
**Impact:** `/health` remains process-level; readiness delegated to Docker healthchecks.

---

### ADR-002 — `/health` is process-level

**Decision:** `/health` confirms only process liveness.
**Impact:** monitoring and health semantics are unambiguous.

---

### ADR-003 — Migrations are explicit and operational

**Decision:** Alembic is never invoked automatically by the API.
**Impact:** schema changes are auditable and reproducible.

---

### ADR-004 — Single source of configuration

**Decision:** `settings.database_url` is the only DB URL source.
**Impact:** avoids drift across Docker/Alembic/code.

---

### ADR-005 — Minimal Conversation/Message domain baseline

**Decision:** implement minimal conversation/message persistence with explicit semantic roles.
**Impact:** stable base for future provider integration.

---

### ADR-006 — Alembic revisions are first-class artifacts

**Decision:** every Alembic revision file must be committed.
**Impact:** prevents image/repo/DB revision graph desynchronization.

---

### ADR-007 — Dev/Prod split via Compose overlays

**Decision:** production uses immutable images; development uses bind-mount overlays.
**Impact:** faster iteration while preserving production reproducibility.

---

### ADR-008 — Best-effort telemetry logging

**Decision:** usage logging must never break request flow; failures are swallowed and logged.
**Impact:** telemetry becomes additive and safe by design.

---

## Appendix A — Troubleshooting patterns (starter)

### A.1 Missing revision / stamped DB

Symptoms:

* `Can't locate revision identified by ...`
* `alembic heads` shows revisions not present in repo

Preferred response:

* reconstruct chain with preserve-chain no-op revisions when necessary
* avoid rewriting history in a way that breaks existing stamped environments

### A.2 Multiple heads

Symptoms:

* `alembic heads` returns more than one head

Preferred response:

* create an explicit merge revision
* verify `current == heads`

### A.3 Validations

Always run:

```bash
docker compose exec -T -w /app/app api alembic current
docker compose exec -T -w /app/app api alembic heads
```

---

**End of LLD — Stable checkpoint Day 8**
