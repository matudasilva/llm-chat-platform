# LLM Chat Platform

Reference architecture for an enterprise-ready LLM Chat backend, focused on transactional guarantees, observability, traceability, and cost-aware operation.

This project models how AI-powered workloads should be integrated and operated in production-like environments with:

* Provider-agnostic orchestration
* Fully transactional write-path design
* Deterministic trace reconstruction
* Structured JSON logging
* Offline cost analytics
* Explicit operational boundaries

> This project intentionally prioritizes architectural clarity, invariants, and operational correctness over feature velocity.

---

## Core Principles

### 1. Transactional Integrity First

`/chat` is the **single authoritative write-path**.

Each request executes within one database transaction:

1. Persist user message
2. Invoke provider via `ChatService`
3. Persist assistant message
4. Persist `UsageEvent`

On failure:

* Business writes are rolled back
* Error telemetry is emitted best-effort (without foreign keys)

No partial persistence is allowed.

---

### 2. Provider-Agnostic Architecture

Providers implement a single async-first contract:

```
ProviderPort.generate(input: ProviderInput) -> ProviderResult
```

`ChatService` orchestrates execution but:

* Has no DB access
* Has no HTTP semantics
* Has no transaction control

This preserves strict separation between domain orchestration and persistence.

---

### 3. Runtime vs Operations Separation

* No DB checks at API startup
* Migrations are never auto-run
* Alembic is executed explicitly
* Docker healthchecks handle readiness

The API process lifecycle remains deterministic.

---

## Observability & Traceability

### Structured JSON Logging (Day 16)

One JSON log line is emitted per HTTP request:

```json
{"request_id":"...","path":"/health","method":"GET","status":200,"latency_ms":1,"app_env":"development"}
```

Characteristics:

* Correlated via `request_id`
* No request/response bodies logged
* Logs to stdout (cloud-friendly)
* No vendor lock-in
* No impact on `/chat` semantics

---

### Deterministic Trace Reconstruction (Day 10)

Every `/chat` execution can be reconstructed from a `request_id`:

* Input message
* Output message
* Latency
* Provider metadata
* Status

This is implemented as a **read-only analysis layer**, without modifying the write-path or schema.

---

### Offline Cost Analytics (Day 15–17)

The platform includes:

* Provider-agnostic cost estimation (`estimate_cost`)
* Static per-provider token rates (configurable)
* Read-only export pipeline over `usage_events`
* Offline aggregation (cost by provider, status, day)

Characteristics:

* No external pricing calls
* No billing coupling
* No schema changes
* Fully reproducible via scripts

This enables deterministic cost reasoning from recorded token usage.

---

## Data Model (Operational View)

### Conversation

Logical chat session container.

### Message

Ordered by `(conversation_id, created_at)`.

### UsageEvent

Foundation for:

* Telemetry
* Cost estimation
* Observability
* Failure audit

Nullable foreign keys allow error telemetry without breaking atomicity.

---

## Tech Stack

* FastAPI (async API)
* PostgreSQL
* SQLAlchemy 2.0 (async)
* Alembic
* Docker / Docker Compose
* Redis (reserved)

---

## Repository Structure

```
app/
  main.py
  api/
  core/
  infra/
  models/
  services/
  scripts/

alembic/
docs/
experiments/
```

---

## Running the Platform

```bash
git clone <repo>
cd llm-chat-platform
cp .env.example .env
docker compose up -d
```

Health check:

```
GET /health
```

---

## Migrations

```bash
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
```

Migrations are never executed automatically.

---

## Testing

```bash
PYTHONPATH=app pytest -q
```

Contract tests validate:

* Provider abstraction
* Guardrails
* Error normalization
* Telemetry best-effort guarantees
* Structured logging
* Cost estimation logic

---

## Architectural Guarantees

* `/chat` remains the only write-path
* One transaction per request
* Provider failures never corrupt business data
* Observability is non-invasive
* No cost logic is coupled to provider execution
* No schema drift through analytics layers

---

## Non-Goals

This project intentionally does not:

* Optimize model quality
* Provide frontend components
* Act as a SaaS product
* Implement billing

It is a correctness-first backend reference system.

---

## Documentation

* `docs/lld_llm_chat_platform_live_doc.md` — live low-level design
* `docs/lld_apendix.md` — deep technical appendices & reproducible evidence

---

## Current State

Day 17 — Observability & Offline Cost Analytics completed.

The platform now demonstrates:

* Transactional LLM write-path
* Provider abstraction layer
* Deterministic traceability
* Structured JSON logging
* Defensive telemetry
* Offline cost analytics
* Strict architectural invariants

---

**This repository is designed as a production-minded LLM backend reference system.**
