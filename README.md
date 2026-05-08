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

## Current State

The current implemented V1.1 runtime surface is:

* `POST /chat` as the single authoritative write-path
* Transactional persistence for non-streaming requests
* SSE streaming with post-stream atomic persistence
* Provider-agnostic execution across OpenAI and Bedrock
* Additive provider resilience and observability
* Config-gated routing seam with static default, signal-based heuristic mode, and best-effort shadow divergence logging
* Read-only conversation inspection endpoints
* Minimal Redis response cache for non-streaming `/chat`
* **Optional** controlled Web Read: `GET /web-read` for fetching and parsing web page content (MVP)
* **Optional** controlled Notion Read: `GET /notion-read/page` for fetching Notion page metadata via MCP (MVP)

Two design choices are worth calling out explicitly for technical review:

* Redis was initially kept **reserved** in the original blueprint to protect a minimal, deterministic transactional baseline before introducing cache semantics. After the `/chat` write-path, streaming boundaries, and observability guarantees were stable, Redis was added as a **best-effort** optimization for successful non-streaming requests only.
* The original V1 blueprint also reserved **ML-based routing** as an architectural direction, including a logistic-regression baseline for cheap-vs-smart model selection. That ML routing layer is **not part of the current implemented V1.1 runtime surface**. The current runtime includes only a **feature-flagged heuristic routing seam** based on provider-agnostic signals, with `static` remaining the default policy.

---

## Architecture Diagram

![LLM Chat Platform architecture](docs/rendered/architecture/module-boundaries-architecture-v1.svg)

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
* Redis (implemented as a best-effort response cache for non-streaming `/chat`; initially reserved in the blueprint until the transactional baseline stabilized)

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

## External Read Capabilities Demo

Two read-only endpoints are available for operator exploration and integration:

- **Web Read:** `GET /web-read?url=<url>` — Fetch and parse web page content
- **Notion Read:** `GET /notion-read/page?page_id=<page_id>` — Fetch Notion page metadata

**Try the demo:**

```bash
# Start Jupyter notebook
jupyter notebook demo_read_capabilities.ipynb
```

Then open the notebook and execute cells to:
- Explore both endpoints interactively
- See request/response shapes
- Test error handling
- Verify endpoint health

**Documentation:**

- Endpoint guide and configuration: `docs/external_read_capabilities.md`
- Troubleshooting common errors: `docs/troubleshooting_external_read.md`
- Error decision table and runbook: `docs/error_decision_table.md`

---

## Controlled Notion Read via MCP (MVP)

Optional read-only capability for accessing Notion page metadata via the Model Context Protocol (MCP).

**Endpoint:** `GET /notion-read/page?page_id=<id>`

**Capabilities (MVP):**

* Read Notion page metadata only (page_id, title, url, created_time, last_edited_time)
* Allowlist enforcement: only configured page IDs are readable
* ID normalization: dashes removed for consistent comparison
* Response sanitization: no page text, blocks, or internal Notion fields

**Setup (requires external notion-mcp-read subprocess):**

```bash
# Clone with submodule
git clone --recursive <repo>

# Configure in .env
NOTION_READ_ENABLED=true
NOTION_MCP_ENABLED=true
NOTION_API_TOKEN=<notion_integration_token>
NOTION_ROOT_PAGE_ID=<root_page_id>
NOTION_ALLOWED_PAGE_IDS=<comma-separated-ids>
NOTION_MCP_SERVER_COMMAND=node
NOTION_MCP_SERVER_ARGS=["/notion-mcp-server/dist/server.js"]
NOTION_MCP_SERVER_CWD=/notion-mcp-server
NOTION_MCP_TIMEOUT_S=10

# Start services
docker compose up -d
```

When running the API in Docker, the image includes Node.js and mounts the local `notion-mcp-read` checkout at `/notion-mcp-server` so the subprocess can be spawned inside the API container.

**HTTP Status Codes:**

* 200: Success (metadata returned)
* 422: Missing or invalid query params
* 403: Page ID not in allowlist
* 502: MCP protocol or upstream Notion API error
* 504: MCP request timeout
* 503: MCP subprocess unavailable
* 500: Unexpected error

**Design Principles:**

* Separate read-only endpoint (never modifies `/chat` or persistence)
* Process-level singleton MCP client (initialized at app startup via `app.lifespan()`)
* Hardcoded tool allowlist (notion_get_page only, no dynamic discovery)
* Error separation by layer (client/service/route for observability)
* Graceful degradation: endpoint unavailable does not affect `/readyz` or `/chat`

**Deferred (Phase 2):**

* Page text extraction (requires block reading)
* Database queries
* Pagination
* Readiness includes MCP health check

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
* Non-streaming `/chat` Redis cache hit, miss, bypass, and failure behavior
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

## Implementation History

The current implemented state is summarized above. The timeline below preserves the incremental evolution of the platform.

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

Day 33 — Minimal Redis response cache for non-streaming `/chat` completed.

* Cache applies only to non-streaming `/chat` requests
* Streaming requests bypass cache reads and writes explicitly
* Redis cache reads and writes are best-effort and never fail the request
* Only successful non-streaming executions are written to cache
* Cache writes happen only after successful transaction commit
* No DB schema, provider, `ChatService`, retry/fallback, or streaming semantics changes were introduced

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
