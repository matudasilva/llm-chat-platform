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

Each request uses a single DB transaction in non-stream mode.
When `stream=true`, tokens are streamed via SSE first and persistence happens in a single DB transaction after the provider completes.

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

Providers implement an async-first contract:

- `ProviderPort.generate(input: ProviderInput) -> ProviderResult`
- `ProviderPort.stream(input: ProviderInput) -> ProviderStreamSession`

`ChatService` orchestrates execution but:

* Has no DB access
* Has no HTTP semantics
* Has no transaction control

This preserves strict separation between domain orchestration and persistence.

#### Provider Resilience Boundary (Day 24)

The provider layer acts as a hardened isolation boundary between external LLM APIs and core domain logic.

Features:

* Controlled retry with exponential backoff
* Retry only for transient failures (429, 5xx, timeout)
* Optional single-hop fallback between configured providers
* No retry for auth or client errors
* Full HTTP + transport error normalization into `ProviderError`
* Structured provider logging events:
  - provider.request
  - provider.retry
  - provider.response
  - provider.error
  - provider.total

Guarantees:

* No API keys leaked
* No raw provider payloads propagated
* No message content logged
* No changes to `/chat` contract
* Fallback remains provider-local and invisible to `ChatService`
* Streaming fallback is allowed only before the first emitted token
* No provider fallback occurs after partial stream emission

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

### Structured Provider Logging (Day 24)

In addition to HTTP-level logs, the provider adapter emits structured JSON events for operational diagnostics:

Events:

* provider.request
* provider.retry
* provider.response
* provider.error
* provider.total
* provider.fallback
* provider.final

These logs include safe metadata only:

- request_id
- provider
- model
- attempt
- max_attempts
- status_code
- latency_ms

Day 30 keeps `provider.request` through `provider.total` as adapter-local lifecycle events and adds
cross-provider operational summaries in `ResilientProvider` via `provider.fallback` and `provider.final`.

Additive Day 30 fields include:

- attempts_used
- failure_kind
- final_provider
- fallback_used

`provider.total` remains adapter-local.
`provider.final` is the cross-provider summary and may include `fallback_from`, `fallback_to`, and
`first_token_emitted` for streaming when relevant.

No user message content or secrets are logged.

This enables production-grade observability without compromising data safety.

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
### Local streaming demo UI

After starting the API container, open:

- `http://localhost:8001/ui` (if port publishing works on your host)

If not, use the API container IP:

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' llm-chat-platform-dev-api-1
```
Then open: http://<IP>:8000/ui
---

## Provider Configuration

Provider selection:

* `PROVIDER=stub|openai|bedrock`
* `PRIMARY_PROVIDER=stub|openai|bedrock` (overrides `PROVIDER` / `provider`)
* `FALLBACK_PROVIDER=stub|openai|bedrock` (overrides `fallback_provider`)

Stub provider knobs:

* `STUB_PROVIDER_MODE=ok|error`
* `STUB_SIMULATED_LATENCY_MS=<int>`

OpenAI provider knobs:

* `OPENAI_API_KEY` (required when `PROVIDER=openai`)
* `OPENAI_MODEL`
* `PROVIDER_TIMEOUT_S`
* `OPENAI_MAX_ATTEMPTS`
* `OPENAI_BACKOFF_BASE_MS`
* `OPENAI_BACKOFF_MAX_MS`

Bedrock provider knobs:

* `BEDROCK_REGION` (required when `PROVIDER=bedrock`)
* `BEDROCK_MODEL` (required when `PROVIDER=bedrock`)
* `BEDROCK_PROMPT_VERSION`
* `BEDROCK_MAX_ATTEMPTS`
* `BEDROCK_BACKOFF_BASE_MS`
* `BEDROCK_BACKOFF_MAX_MS`
* `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` (optional; standard AWS credential resolution also applies)

Provider configuration is centralized in `app/core/settings.py`.
Primary/fallback precedence is handled in settings validation and consumed by the provider factory.

## Migrations

```bash
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
```

Migrations are never executed automatically.

---

## Testing

Canonical green command:

```bash
docker compose -f docker-compose.dev.yml run --rm -e PROVIDER=stub api python -m pytest -q
```

Minimal CI baseline (Day 32):

* GitHub Actions workflow: `.github/workflows/ci.yml`
* Narrowed deterministic pytest baseline:

```bash
python -m pytest -q \
  tests/core \
  tests/api/test_health_readyz.py \
  tests/api/test_request_ids.py \
  tests/api/test_request_size_limit.py \
  tests/api/test_structured_logging.py
```

* Default Docker build validation:

```bash
docker build -t llm-chat-platform:ci .
```

Current coverage includes:

* `/chat` non-stream regression
* Streaming SSE smoke test (`token`, `done`, `error`)
* Read-only conversation inspection endpoints
* Health and readiness endpoints
* Request ID propagation
* Request size limit enforcement
* Structured logging behavior
* Telemetry best-effort guarantees
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

* Provide a frontend application or build pipeline
  * A minimal single-file demo UI is available at `GET /ui` for local streaming demos
* Optimize model quality
* Provide frontend components
* Act as a SaaS product
* Implement billing

It is a correctness-first backend reference system.

---

## Documentation

* `docs/lld_llm_chat_platform_live_doc.md` — live low-level design
* `docs/lld_apendix.md` — deep technical appendices & reproducible evidence

## Architecture diagram workflow

Mermaid diagrams may exist under `docs/working/diagrams/` as design-time artifacts used for architectural context during implementation, refactoring, and documentation work.

They are not product or runtime functionality unless explicitly stated.

When architecture, request flow, provider behavior, streaming or fallback behavior, or persistence flow changes, the corresponding diagram should be reviewed and updated if needed.

## Local Mermaid rendering

Mermaid source files under `docs/working/diagrams/` may be rendered locally into SVG artifacts for documentation and design review.

Local rendering may require a user-specific `puppeteer-config.json`. The repository includes `puppeteer-config.example.json` as a template; copy it locally to `puppeteer-config.json` and adjust the browser path for your machine.

`puppeteer-config.json` is intentionally ignored from version control and should remain a local-only file.

---

## Current State

Day 29 — MVP hardening for minimal provider resilience completed.

* `POST /chat` supports SSE streaming behind `stream=true`
* OpenAI and Bedrock both fit through the same provider abstraction
* Bedrock supports `generate()` and `stream()` without changing `/chat`, `ChatService`, or the DB schema
* A minimal resilience wrapper at the `ProviderPort` boundary supports transient retry + single-hop fallback
* Fallback is config-driven through `PRIMARY_PROVIDER` / `FALLBACK_PROVIDER`
* Streaming SSE emits `token`, `done`, and `error` events
* Chunk granularity depends on provider emission behavior and may arrive as a single larger `token` event
* Streaming usage metadata is provider-driven and remains consistent when persisted
* Provider-to-provider fallback is allowed only before the first emitted token
* No fallback occurs after partial stream emission; the stream terminates with error
* Minimal demo UI at `GET /ui` (single static HTML)
* Focused tests cover retry, fallback, streaming fallback boundaries, and config precedence
* Provider configuration is centralized in `app/core/settings.py`
* Provider factory no longer reads environment variables directly
* Structured provider retry/error normalization remains confined to provider adapters

Day 30 — Provider observability hardening completed.

* Structured retry/fallback observability was extended with additive provider logging only
* `ResilientProvider` now emits cross-provider operational summaries via `provider.fallback` and `provider.final`
* Adapter-local totals remain distinct from cross-provider summaries
* No behavioral, API, schema, `/chat`, `ChatService`, route, or retry-semantics changes were introduced
* Focused Day 30 validation covered resilient provider observability plus OpenAI and Bedrock provider logging

Day 31 — Conversation read-endpoint test reliability hardening completed.

* `tests/api/test_conversations_read_endpoints.py` was stabilized with a strictly test-local change
* The test now stubs `ConversationQueryService` instead of depending on environment-coupled DB/DNS behavior
* No production route, domain, DB schema, provider, or streaming changes were made

Day 32 — Minimal CI baseline added.

* `.github/workflows/ci.yml` introduces a single `validate` job for push and pull request events
* CI installs runtime and dev test dependencies, runs a narrowed deterministic pytest baseline, and validates the default Docker build path
* No production code, Dockerfile, Makefile, runtime, provider, `/chat`, `ChatService`, DB schema, persistence, streaming, or telemetry behavior changed

---

### Read-only inspection endpoints (Day 23)

The platform exposes read-only endpoints to inspect persisted conversations:

- `GET /conversations?limit=20&offset=0`
  - Returns conversation metadata plus `message_count` (no message content).
- `GET /conversations/{conversation_id}`
  - Returns conversation metadata plus ordered messages (`created_at ASC`).

Constraints:
- No write operations
- `/chat` remains the single authoritative write-path
- No database schema changes



**This repository is designed as a production-minded LLM backend reference system.**
