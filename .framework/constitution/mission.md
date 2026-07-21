**Authorship:** operator + agent (brownfield reverse engineering)
**Date:** 2026-07-21
**Version:** v1

# Mission — LLM Chat Platform

## What it is

A portfolio-grade backend platform for LLM chat workloads: a provider-agnostic,
multi-tenant chat API with a transactional write-path, SSE streaming, best-effort
caching and telemetry, and cost-aware usage accounting. A minimal React/Vite web
client lives in a separate repository (`llm-chat-platform-web`).

## Who it serves

- **Primary:** the operator, as a reference architecture demonstrating how AI
  workloads are integrated and operated in production-like environments.
- **Secondary:** technical reviewers evaluating architectural decisions,
  invariants, and operational evidence.
- **Runtime:** tenant-scoped API consumers (the web client today; other tenants'
  clients by design).

## Why it exists

Most LLM chat implementations couple business logic to a single provider, treat
persistence as best-effort, and leave cost and observability as afterthoughts.
This project exists to prove the opposite discipline: architectural clarity,
stable ports, transactional guarantees, and reproducible evidence take priority
over feature velocity.

## Scope

**Included:**
- `/chat` as the single transactional write-path (non-streaming and SSE).
- Provider abstraction (`ProviderPort`) with Stub, OpenAI and Bedrock adapters,
  plus `ResilientProvider` single-hop fallback.
- Atomic persistence: `Conversation`, `Message`, `UsageEvent`.
- Read endpoints separated from the write-path: conversations, usage events.
- External read/write capabilities behind explicit contracts: controlled web
  read, Notion read via MCP, Notion write with a safety contract.
- Foundational multitenancy: `tenant_id` propagation via pure-ASGI middleware,
  service-layer scoping, tenant-namespaced cache.
- Best-effort Redis response cache and structured JSON logging.
- Explicit Alembic migrations (never auto-run at startup).
- Container-image promotion path to a PaaS runtime, with a staging environment.
- Planned: retrieval (RAG) as a separate read capability, routing policies,
  and an AI Green extension for energy/CO2e accounting.

**Excluded:**
- Authentication and authorization as a product feature (currently declared
  no-auth; JWT signature verification is documented debt).
- The frontend implementation (separate repository, separate release cycle).
- Infrastructure-as-code and automated deploy workflows (deployment is manual).
- Advanced telemetry backends (OpenTelemetry, MLflow, Prometheus) until the
  phases that require them.
- Any provider-specific behavior in routes or domain services.

## Related

- Planning source of truth: Notion Master Project Document (state + roadmap).
- Decisions: `docs/adr/`.
- Effective architecture: `README.md`, `docs/lld_*`.
- Technical detail: [[tech-stack]] · Sequencing: [[roadmap]]
