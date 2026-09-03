# ADR-004: Tenant Scoping for Read Endpoints — Application-Layer Filter

**Date:** 2026-07-01
**Status:** Accepted
**ORQ reference:** ORQ-18.2
**Superseded by / Supersedes:** Amended by ADR-011 (§3 — `list_messages_for_conversation` now filters on `tenant_id`; ORQ-38 became the unguarded second caller this ADR anticipated)

---

## Context

ORQ-18 (ADR-003) introduced multitenancy as a transversal foundation: `tenant_id` was added to the `conversations` and `messages` tables, the `/chat` write path scopes all new records to the requesting tenant, and the Redis cache is namespaced per tenant.

The read endpoints (`GET /conversations` and `GET /conversations/{id}`) were not updated during ORQ-18. Neither endpoint calls `get_tenant_id()`, and `ConversationQueryService` has no `tenant_id` parameter in any of its three methods. The result is a cross-tenant data leak: any tenant can enumerate all conversations in the database and retrieve any conversation's messages, regardless of the tenant that created it.

This gap was confirmed by testing on 2026-06-30. The fix is scoped: no new columns, no migrations, no provider or streaming changes — `tenant_id` already exists in both tables.

ADR-003 §3 documents "application-layer scoping" as the enforcement approach with RLS deferred to ORQ-21. This ADR extends that decision to the read path, applying the same pattern established for the write path.

---

## Decision

We add `tenant_id: str` as a required parameter to all three methods of `ConversationQueryService` and propagate the value from `get_tenant_id()` at the route layer.

### 1. `list_conversations(limit, offset, tenant_id)`

Add `.where(Conversation.tenant_id == tenant_id)` to the existing query. This scopes the paginated list to only conversations owned by the requesting tenant.

### 2. `get_conversation(conversation_id, tenant_id)`

Fetch the conversation by ID as before. After the fetch, if the result is not `None` and `conv.tenant_id != tenant_id`, return `None`. The route's existing `404` handler covers this case. Returning `None` rather than raising an exception inside the service preserves the service's freedom from HTTP semantics (documented invariant in AGENTS.md). The response to a cross-tenant request is indistinguishable from a not-found response — no information is leaked about whether the resource exists.

### 3. `list_messages_for_conversation(conversation_id, tenant_id)`

No direct filter is added to the messages query. Messages are fetched only after `get_conversation` has already validated tenant ownership. The `tenant_id` parameter is accepted for consistency and future-proofing (e.g., if `list_messages_for_conversation` is ever called from a context where conversation ownership was not pre-validated). The route always calls `get_conversation` before `list_messages_for_conversation`, so the security guarantee is held at the route level.

### 4. Route layer

Both route handlers import `get_tenant_id` from `app.http.middleware.tenant` and call it at the top of the handler. The returned `tenant_id` is passed to every `ConversationQueryService` call. No other change to the route handlers.

### 5. RLS remains deferred

Row-level security at the PostgreSQL level is not implemented here. This is unchanged from ADR-003. Application-layer enforcement is the sole control until ORQ-21.

---

## Consequences

### Positive

- Cross-tenant read leak is closed. A tenant can no longer enumerate or retrieve another tenant's conversations.
- Zero schema changes — `tenant_id` column already exists.
- No change to ProviderPort, ResilientProvider, streaming path, or persistence atomicity.
- The `"default"` fallback means callers without `X-Tenant-ID` continue to see only `"default"` conversations (backward-compatible).
- Consistent with the enforcement pattern already established for the write path (ADR-003 §6).

### Negative / Trade-offs

- Application-layer filter is still not a security boundary. A compromised application or direct DB connection bypasses it. Documented debt; resolved by RLS in ORQ-21.
- `list_messages_for_conversation` does not add a redundant DB-level filter. This is a deliberate trade-off: the route is the single call site, and adding a redundant filter in the service would encode an assumption about conversation-ownership pre-validation that only holds today. If the method gains additional callers in the future, the `tenant_id` parameter serves as a reminder to add the filter.

---

## Alternatives Considered

### Alternative A: PostgreSQL Row-Level Security

Add `ALTER TABLE conversations ENABLE ROW LEVEL SECURITY` and define policies that restrict reads to rows matching the current session's `tenant_id`.

**Rejected** for this ORQ. RLS requires the DB session to carry the tenant context (e.g., via `SET LOCAL app.tenant_id = '...'` before each query), which would require changes to `infra/db.py` and the session lifecycle. That is a larger change than the scope of this ORQ. Explicitly planned for ORQ-21 per ADR-003.

### Alternative B: SQLAlchemy Session-Level Query Filter

Use SQLAlchemy's `with_loader_criteria` or a custom `Query` subclass to inject `tenant_id` filters automatically into every ORM query.

**Rejected** because it introduces implicit magic that is difficult to test, debug, and audit. Explicit parameters in service methods are visible in call sites, type-checked, and easy to verify in code review.

### Alternative C: Middleware-Level Filtering

Intercept all `GET /conversations*` requests in `TenantMiddleware` and return 403/404 before they reach the route.

**Rejected** because middleware does not have access to the database or the resource's `tenant_id`. Cross-tenant enforcement requires a DB lookup, which belongs in the service or persistence layer, not in HTTP middleware.

---

## Evidence

- Confirmed cross-tenant leak: testing on 2026-06-30 — GET /conversations without X-Tenant-ID returns all conversations
- ADR-003: row-level multitenancy with application-layer enforcement; RLS deferred to ORQ-21
- AGENTS.md invariants: ConversationQueryService must not carry HTTP semantics; ProviderPort and streaming must not be touched
- ORQ-18 commits: `f2108e8`, `27678ff`, `bdd6d35` — write path scoping already implemented
- ORQ-18.2 implementation: commit TBD (Codex execution)
