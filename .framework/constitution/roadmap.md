**Authorship:** operator + agent (derived from the Notion Master Project Document and V2 ORQ history)
**Date:** 2026-07-21
**Version:** v1

# Roadmap — LLM Chat Platform

> Ordering is subject to revision. Deviating is not drift as long as the change is
> recorded in an ADR. The authoritative live state lives in the Notion Master
> Project Document; this file is the local AIT V3 planning surface.

## Phase 0 — V1.1 clean closure — ✅ done

Left V1.1 without blocking debt and installed the anti-drift machinery: `docs/adr/`
with the same-PR rule, a CI reconciliation check, ORQ history reconciliation, and
the `v1.1-stable` tag.

## Phase 1 — V2 core — ✅ substantially delivered

- Retroactive ADR-001: capabilities-first instead of orchestrator-first.
- External capabilities: controlled web read, Notion read via MCP, Notion write
  behind a safety contract.
- Foundational multitenancy (ADR-003): `tenant_id` on `Conversation`/`Message`,
  pure-ASGI `TenantMiddleware` registered last (Starlette LIFO), `ContextVar`
  propagation, tenant-namespaced cache with full-history fingerprint.
- Cross-tenant read-path leak closed via service-layer scoping (ADR-004).
- Local test suite hermetized.
- Minimal chat frontend, tenant-aware, in a separate repository; SSE framing,
  GFM tables and message-order fixes.
- Dev→Prod Option A (ADR-005): image pipeline to GHCR, thin deploy repository,
  staging on PaaS with serverless Postgres and Redis, end-to-end SSE verified.

**Still open in this phase:**
- Execution Orchestrator + Tool Calling Engine, and the `ChatService` refactor
  that uses them — deferred by ADR-001, not cancelled.
- Default provider moved off `stub` to a live-validated OpenAI/Bedrock.
- Backend sequencing via `GENERATED ALWAYS AS IDENTITY` instead of
  timestamp-based ordering (proposed follow-up from the SSE fix).

## Phase 2 — Retrieval (RAG) + Routing — next

RAG enters as a **separate read capability**; it does not touch the `/chat`
invariant.

1. **RAG baseline** — split by the operator across two ORQs (see ORQ-21 §Scope):
   - ✅ done (ORQ-21, closed locally 2026-08-03): pgvector on the existing
     Postgres behind a `VectorStorePort`; API-first `EmbeddingPort`
     (OpenAI `text-embedding-3-small`, 1536 dims); hybrid retrieval (semantic +
     keyword, RRF fusion); tenant-scoped corpus and Postgres RLS against a
     genuinely unprivileged role (settles the ADR-004 §5 deferral for the RAG
     corpus specifically — `conversations`/`messages` RLS is still open, see
     `docs/adr/004-tenant-scoping-read-endpoints.md`).
   - Open (ORQ-22, not yet started): query rewriting via `ProviderPort`,
     cross-encoder reranking via Bedrock, reproducible evaluation harness with
     MLflow tracking, golden dataset, OpenTelemetry-ready spans. Prerequisite:
     a working AWS credential pair (revoked in ORQ-20, not yet replaced).
   - **Not yet scoped in any ORQ** (drift flagged by `fw-replan`, 2026-08-03):
     the actual answer-generation step — reusing `ProviderPort`/
     `ResilientProvider` with retrieved context in `ProviderInput.metadata` to
     produce a synthesized answer, including the system prompt that step would
     run under. ORQ-21 shipped retrieval only; ORQ-22 as currently scoped
     covers retrieval *quality* (rewriting, reranking, evaluation), not
     synthesis. Needs its own ORQ or an explicit scope addition before this
     roadmap item can be marked done.
2. **Routing evidence dataset** — `RoutingPolicy` interface with heuristic and
   static implementations by default; collect real signal before any model.
3. **Offline ML routing baseline** — a simple, explainable model, only if the
   evidence dataset shows real signal.

Reusable precedent: for broad or multilingual queries, reranking alone is not
enough when the initial candidate set is poor — intent detection plus an
"overview" canonical query expansion plus path-priority reranking is the pattern
that worked. Relevant here because project documentation is bilingual.

## Phase 3 — AI Green extension

Fits as an extension, not a rewrite; each piece maps to an existing component.

- Per-request energy/CO2e telemetry extending `UsageEvent` / `ProviderResult`.
- Carbon-aware, small-first routing extending `RoutingPolicy`.
- Semantic caching extending the Redis layer.
- Green LLMOps dashboard on MLflow/Grafana.
- Horizon: a carbon-aware scheduler with batch/deferred modes.

Transversal multitenancy enables the per-tenant accounting (tokens, cost, energy,
CO2e) this phase depends on.

## Open decisions

- Energy/CO2e estimation methodology per request.
- Default model and routing escalation thresholds.

## Decisions closed by ORQ

- **Embedding provider and dimension** (ORQ-21, 2026-07-29): OpenAI
  `text-embedding-3-small` at 1536 dimensions, a corpus-level constant
  independent of each tenant's chat provider. Full rationale:
  `docs/adr/006-rag-corpus-embeddings-and-rls.md` §1.

## Related

Purpose and boundaries: [[mission]] · Constraints and invariants: [[tech-stack]]
