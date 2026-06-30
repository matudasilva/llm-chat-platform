# ADR-003: Multitenancy Transversal Foundation — Row-Level with Deferred RLS

**Date:** 2026-06-30
**Status:** Accepted
**ORQ reference:** ORQ-18
**Superseded by / Supersedes:** —

---

## Context

The platform is currently single-tenant. All persistent models (`Conversation`, `Message`, `UsageEvent`) have no tenant dimension. The Redis cache uses global keys with no tenant namespace. Structured logs carry no tenant field. The system has one implicit tenant: every request shares the same data space.

The master continuity document (Notion, "Proyecto LLM Chat Platform ES") declared multitenancy as a **transversal concern from V2 onward**, meaning every subsequent layer — frontend (ORQ-19), deploy pipeline (ORQ-20), RAG corpus (ORQ-21), routing evidence (ORQ-22) — must be built with tenant isolation in mind. If multitenancy is introduced after those layers exist, each would require structural rewrites.

Two additional latent issues were identified during V1.1 audit:

1. **Cache fingerprint bug**: the Redis key was computed from only the last message, not the full conversation history, causing potential cross-conversation cache collisions.
2. **Cache namespace gap**: even with a correct fingerprint, a global key allows cross-tenant cache hits — tenant A's response could be served to tenant B for the same message content.

Both issues are resolved in this ORQ as part of the multitenancy foundation.

---

## Decision

We implement **row-level multitenancy with application-layer enforcement and deferred RLS**.

The approach has five components:

### 1. Data model: tenant_id column

Add `tenant_id VARCHAR NOT NULL DEFAULT 'default'` to `conversations` and `messages` tables via a reversible Alembic migration. Existing rows receive the value `"default"`. A composite index `(tenant_id, created_at)` is added to `conversations` to support efficient per-tenant queries.

### 2. Request context: middleware extraction

A `TenantMiddleware` extracts `tenant_id` at the HTTP boundary in the following priority order:
- **(a)** Header `X-Tenant-ID` — explicit, direct
- **(b)** Claim `tenant_id` in a Bearer JWT — for authenticated flows
- **(c)** Fallback: `"default"` — preserves backward compatibility for single-tenant callers

The extracted value is stored in `request.state.tenant_id` and propagated downstream. The middleware is registered in `app/main.py`.

### 3. Persistence: application-layer scoping

The `/chat` write path reads `request.state.tenant_id` and passes it to `ChatService`, which sets it on the `Conversation` and `Message` ORM objects at creation time. No changes to `ProviderPort`, `ResilientProvider`, or the SSE streaming path — those are invariants per `AGENTS.md`.

### 4. Cache: namespaced keys + fingerprint fix

Redis key changes from `chat:response:{sha256}` to `chat:response:{tenant_id}:{sha256}`. The fingerprint changes from hashing only the last message to hashing the full message list: `hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()`. This resolves both the namespace gap and the fingerprint collision bug simultaneously.

### 5. Telemetry: tenant_id as first-class log field

`tenant_id` is added as a top-level field to all structured JSON log events (`chat.*`, `provider.*`, `cache.*`). No OpenTelemetry instrumentation in this ORQ — that is deferred to Phase 2.

### RLS deferred

Row-level security at the PostgreSQL level is **not implemented in this ORQ**. The application-layer filter is the first enforcement step. RLS is explicitly planned for **ORQ-21**, when per-tenant corpus scoping for RAG requires a strong data-layer guarantee. This is documented as explicit technical debt.

---

## Consequences

### Positive

- Every subsequent ORQ (frontend, deploy, RAG, routing) inherits tenant awareness without structural changes.
- Cross-tenant cache hits are eliminated by namespace isolation.
- The fingerprint bug is fixed as a byproduct: cache collisions across conversations are no longer possible.
- `tenant_id` in logs enables per-tenant observability immediately.
- The `"default"` fallback means zero breaking changes for existing single-tenant callers.
- The Alembic migration is reversible: `downgrade()` drops the column cleanly.

### Negative / Trade-offs

- **Application-layer filter is not a security boundary.** A compromised application layer or a direct DB connection bypasses tenant isolation. This is explicit debt, resolved by RLS in ORQ-21.
- **`"default"` is not a real tenant.** It is a migration artifact. Any future tenant enrollment must replace `"default"` rows or treat the default tenant as a legacy namespace.
- **JWT parsing in middleware is best-effort.** If the token is malformed or the claim absent, fallback to `"default"` applies silently. This is acceptable for MVP but should be hardened in a dedicated auth ORQ.
- `UsageEvent` is intentionally excluded from this ORQ: it has no foreign key to `conversations`, and adding `tenant_id` to it requires a separate analysis of the cost reporting pipeline. Documented as ORQ-18 deferred debt.

---

## Alternatives Considered

### Alternative A: Schema-per-tenant

Each tenant gets its own PostgreSQL schema (or database). Migrations run per-tenant. Complete isolation at the data layer.

**Rejected** because: operationally complex for the current scale (migrations must run N times per tenant, connection pooling becomes non-trivial, Alembic's default tooling is schema-agnostic); provides no benefit until the number of tenants justifies the overhead; cannot be adopted incrementally without a full rewrite. Revisit if tenant count exceeds O(100) with strict isolation SLAs.

### Alternative B: Application-filter-only without planned RLS

Add `tenant_id` to models and filter at the application layer, with no roadmap commitment to RLS. The approach is identical to the chosen decision in implementation, but differs in intent: RLS would be treated as optional rather than planned.

**Rejected** because: the master continuity document explicitly requires a path to strong tenant isolation for the RAG phase. Leaving RLS as unplanned debt would risk deferring it indefinitely. By committing RLS to ORQ-21, the design remains honest about the current limitation while maintaining a concrete closure path.

---

## Evidence

- Master continuity document: "Proyecto LLM Chat Platform ES" (Notion) — multitenancy declared transversal from V2
- ADR-002 Amendment (2026-06-27) — ORQ-18 confirmed as multitenancy foundation slot
- V1.1 audit: cache fingerprint bug documented in `docs/lld_llm_chat_platform_live_doc.md` §3.3
- `AGENTS.md` invariants: ProviderPort, streaming, and persistence atomicity must not be modified
- RLS target: ORQ-21 (RAG baseline) — tenant-scoped corpus requires DB-level isolation
