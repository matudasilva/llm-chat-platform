**Authorship:** operator + agent (derived from manifests and real repository structure)
**Date:** 2026-07-21
**Version:** v1

# Technical stack — LLM Chat Platform

## Stack

**Runtime and language**
- Python 3.13 (`Dockerfile`: `python:3.13-slim`)
- FastAPI 0.128 + Uvicorn (standard extras), async throughout

**Data**
- PostgreSQL via SQLAlchemy 2.0 async + `asyncpg`
- Alembic for migrations (config at `app/alembic.ini`, not repository root)
- Redis (`redis>=5.0`) as a best-effort response cache

**Providers and integrations**
- OpenAI over `httpx`; AWS Bedrock over `boto3`
- Stub provider for deterministic tests
- Notion via MCP (`mcp>=1.27.0`)

**Configuration**
- `pydantic` v2 + `pydantic-settings`, centralized in `app/core/settings.py`

**Packaging and local ops**
- Docker + Docker Compose (`docker-compose.yml` prod, `docker-compose.dev.yml` dev)
- Pinned dependencies in `app/requirements.txt` / `app/requirements.lock`

**Delivery**
- CI builds and publishes a versioned container image to GHCR
- Staging runs on a managed PaaS with serverless Postgres and Redis
- A thin, separate deploy repository holds only deployment artifacts;
  promotion is a tag bump. Rollback is re-pinning the previous tag.

**Related repositories**
- `llm-chat-platform-web` — React + Vite SPA, independent release cycle
- `llm-chat-platform-deploy` — deployment artifacts only

## Structure (real, not aspirational)

```
app/api/routes/    chat, conversations, usage_events, web_read, notion_read, notion_write
app/core/          settings, logging, domain, providers/, utils
app/services/      chat_response_cache, conversation_query_service, readiness,
                   routing_signals, trace, usage_events, usage_logger,
                   web_read, notion_read/write (+ clients)
app/http/          request context, middleware/ (TenantMiddleware, CORS, guards)
app/infra/         db/, schemas/, redis client
app/models/        conversation, message, usage_event
app/alembic/       deterministic migration chain
docs/adr/          ADR-001 … ADR-005
```

## Constraints

- The framework apparatus (`.framework/`, `.claude/`) is local-only except for
  the Constitution, which is explicitly versioned. The repository is **public** —
  no credentials, hostnames, project identifiers or endpoints in versioned files.
- Migrations are a distinct release step and require the explicit config path
  (`alembic -c app/alembic.ini upgrade head`).
- Tests must be hermetic and deterministic: no real providers, no reliance on
  ambient process environment variables.
- Repository artifacts (code, docs, commits, tests) are written in English;
  `orq_language: en`.
- The production and dev Compose stacks share host port mappings — they must not
  run in parallel on the same machine.
- Cache keys are tenant-namespaced (`chat:response:{tenant_id}:{sha256}`) and
  fingerprint the full conversation history, not just the last message.

## Technical invariants

Changing any of these requires an explicit ADR in `docs/adr/`, in the same PR as
the implementation (see `AGENTS.md`, `docs/adr/README.md`).

1. `/chat` is the only write-path; read capabilities stay separate.
2. `ProviderPort` is the stable contract. New context (e.g. RAG) travels through
   `ProviderInput.metadata` and never changes the signature.
3. Persistence is transactional; partial persistence is not allowed.
4. Telemetry and tracing are best-effort and never alter write-path semantics.
5. Migrations run explicitly, never at application startup.
6. No provider-specific logic in routes or domain services.
7. Streaming must not break: SSE contract is `token`, `done`, `error`.
8. Fallback happens only before the first emitted token — never mid-stream.
9. Resilience and observability are additive, not invasive.
10. Tenant isolation is enforced server-side; `tenant_id` is never required in
    read-endpoint payloads.

## Known debt (not invariant)

- Row-Level Security in Postgres — deferred (ADR-004), due with the RAG corpus.
- JWT signature verification — the system is declared no-auth today.
- `UsageEvent.tenant_id` — deferred pending cost-pipeline analysis.
- No IaC; deployment is manual. CI validates build and guardrails only.

## Related

Purpose and boundaries: [[mission]] · Sequencing: [[roadmap]]
