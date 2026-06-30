# CLAUDE.md — LLM Chat Platform Codebase Guide

## Overview

This is a portfolio-grade backend platform for LLM chat workloads. The project emphasizes architectural clarity, provider abstraction, observability, cost awareness, reproducibility, and minimal-diff iterative delivery.

**Current version:** V1.1 (baseline documented in Task-1)  
**Framework:** V2 adoption (structural, non-functional)

---

## Authoritative Documents

These documents are the source of truth and must remain aligned with implementation:

- `README.md` — Architecture overview and runtime surface
- `docs/lld_llm_chat_platform_live_doc.md` — Low-level design (42KB)
- `docs/lld_apendix.md` — Technical appendices and reproducible evidence (53KB)
- `docs/v1_1_closure.md` — V1.1 closure baseline (2026-04-17)
- `AGENTS.md` — Project-specific working rules and invariants

---

## Repository Structure

```
llm-chat-platform/
├── app/
│   ├── main.py                    # FastAPI application entry
│   ├── api/                       # HTTP layer (routes, handlers)
│   ├── core/                      # Domain logic (providers, settings, logging)
│   ├── services/                  # Domain services (ChatService, routing, cache)
│   ├── infra/                     # Infrastructure (DB, Redis)
│   ├── models/                    # ORM models (Conversation, Message, UsageEvent)
│   ├── http/                      # HTTP utilities (request context)
│   └── scripts/                   # Operational scripts (cost reports, tests)
├── alembic/                       # Database migrations (Alembic)
├── tests/                         # Test suites
├── docs/                          # Documentation (LLD, appendices)
├── Dockerfile                     # Production image
├── docker-compose.yml             # PROD (API + PostgreSQL + Redis)
├── docker-compose.dev.yml         # DEV (with bind mounts)
└── .framework/                    # Framework V2 operational structure
```

---

## Core Invariants (Non-Negotiable)

These invariants are documented in `AGENTS.md` and must be preserved across all changes:

- `/chat` is the **only write-path**
- **Persistence remains atomic** (one transaction per request, 4-step pattern)
- **Provider-agnostic architecture** (no provider-specific logic in routes)
- **Domain services are provider-agnostic** (ChatService has no provider coupling)
- **No provider-specific logic in routes or domain services**
- **Telemetry is best-effort** (failures do not break business logic)
- **Streaming must not break** (SSE contract: token, done, error)
- **Fallback before first token only** (no fallback after partial stream emission)
- **Resilience is additive, not invasive** (observability does not change behavior)

If a proposed change violates any invariant, it must be rejected or adjusted.

---

## Tech Stack

- **FastAPI** (async API framework)
- **PostgreSQL** (persistent data store)
- **Redis** (best-effort response cache, non-streaming `/chat` only)
- **SQLAlchemy 2.0 async** (ORM)
- **Alembic** (database migrations, manual execution required)
- **Docker + Docker Compose** (containerization and local development)

---

## Development Workflow

### Local Setup

```bash
# Clone and enter repo
git clone <repo>
cd llm-chat-platform

# Copy environment template
cp .env.example .env

# Start services (API + DB + Redis)
docker compose up -d

# Verify API is running
curl http://localhost:8000/health
```

### Running Tests

```bash
# Full test suite (requires Stub provider)
docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q

# Minimal CI baseline
python -m pytest -q tests/core tests/api/test_health_readyz.py tests/api/test_request_ids.py tests/api/test_request_size_limit.py tests/api/test_structured_logging.py
```

### Database Migrations

Migrations are **never auto-run**. Always execute explicitly:

```bash
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
```

### Code Guidelines

- **English only** for code, config, commit messages, inline TODOs, test names
- **Minimal-diff mindset:** prefer small, clear changes over large refactors
- **Prefer tests over docs** for behavior verification
- **Prefer isolation over coupling** in tests (use stubs, avoid external dependencies)
- **Preserve boundaries:** avoid crossing architectural layers without explicit reason

## Architecture Decisions (ADRs)

Before implementing an architecture change or direction pivot, review `docs/adr/` for related prior decisions.
If the task requires a new decision, write the ADR in `docs/adr/NNN-title.md` using `docs/adr/template.md`.
The ADR must be included in the same PR as the code that implements it, never separately.
See `docs/adr/README.md` for the full ADR workflow.

---

## Key Files and Their Roles

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app initialization, middleware, lifespan |
| `app/api/router.py` | Main HTTP router, route registration |
| `app/core/settings.py` | Centralized configuration (providers, environment) |
| `app/core/logging.py` | Structured JSON logging (HTTP + provider events) |
| `app/services/chat_service.py` | Domain orchestration (provider-agnostic) |
| `app/services/routing_signals.py` | Signal extraction for routing policies |
| `app/core/providers/` | Provider adapters (ProviderPort, Stub, OpenAI, Bedrock, Resilient) |
| `app/infra/db.py` | SQLAlchemy async engine and session lifecycle |
| `app/infra/redis_client.py` | Redis client for best-effort cache |
| `app/models/` | ORM models (Conversation, Message, UsageEvent) |
| `alembic/versions/` | Deterministic migration chain |
| `docs/lld_llm_chat_platform_live_doc.md` | Complete low-level design |
| `docs/lld_apendix.md` | Technical appendices and evidence |

---

## Common Tasks

### Add a New Provider

1. Implement `ProviderPort` interface (generate + stream methods)
2. Add configuration in `app/core/settings.py`
3. Register in provider factory
4. Add contract tests in `tests/core/`
5. Update `AGENTS.md` and documentation if behavior changes

**Constraint:** Provider must remain behind ProviderPort abstraction. No provider-specific logic in routes.

### Add a New Read Endpoint

1. Implement query service (if needed)
2. Add route handler in `app/api/`
3. Preserve `/chat` as the only write-path
4. Add tests in `tests/api/`
5. Update documentation if scope changes

### Change Observability

1. Add structured logging in the appropriate layer (HTTP, provider, domain)
2. Update `app/core/logging.py` if new event types
3. Document event schema in `docs/lld_apendix.md`
4. Add telemetry regression tests

**Constraint:** Observability must be non-invasive and best-effort (failures do not break business logic).

### Optimize Cache or Performance

1. Update `app/services/chat_response_cache.py` or relevant service
2. Ensure best-effort semantics (cache failures do not break `/chat`)
3. Document behavior change in README and LLD
4. Add performance regression tests

---

## Testing Strategy

- **Unit tests** for isolated functions (utilities, cost calculations)
- **Contract tests** for provider adapters (test against ProviderPort)
- **Integration tests** for end-to-end flows (use stubs, avoid real providers)
- **Determinism** is non-negotiable (tests must pass reliably in CI)

Key test suites:
- `tests/core/` — Domain logic and services
- `tests/api/` — HTTP layer and routes
- `tests/fixtures/` — Shared test utilities and stubs

---

## Framework V2 Governance

This repository adopts Framework V2 for **operational governance only**. No functional changes to the product:

- `.framework/project-config.yml` — Operational configuration
- `.framework/framework-version` — Framework version tracking
- `.framework/context.md` — Operational context and constraints
- Project Context Source: Notion `Proyecto LLM Chat Platform ES`
- Governance Sync Targets: `Framework Learning / Insights`, `ORQ Dashboard`, and optional project status updates
- Reading from a Project Context Source does not imply creating ORQs in that source. ORQ preparation and execution remain local/repo framework operations unless explicitly configured otherwise.

**Non-functional:** These files do not change runtime behavior, persistence, providers, or API contracts.

---

## When to Escalate

Escalate to project lead if:
- A change violates any invariant in `AGENTS.md`
- A change affects `/chat` contract or semantics
- A change affects provider abstraction or contracts
- A change affects persistence or streaming boundaries
- A change breaks observability or traceability (request_id, logging)
- A change requires architectural redesign

---

## Quick References

- **Invariants:** `AGENTS.md` (core system non-negotiables)
- **Architecture:** `README.md` and `docs/lld_llm_chat_platform_live_doc.md`
- **Evidence:** `docs/lld_apendix.md` (reproducible tests and behavior)
- **Operational Rules:** `AGENTS.md` (scope discipline, working mode, change boundaries)
- **V1.1 Baseline:** `docs/v1_1_closure.md` (validation and continuity)

---

**Last updated:** 2026-04-27 (Framework V2 adoption, non-functional)
