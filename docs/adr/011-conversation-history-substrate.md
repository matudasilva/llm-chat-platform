# ADR-011: Conversation History Substrate — Ownership-Validating Port, Forward-Only Ordering

**Date:** 2026-09-03
**Status:** Accepted
**ORQ reference:** ORQ-38
**Superseded by / Supersedes:** Amends ADR-004 §3

---

## Context

`/chat` sends the provider exactly one message. Verified 2026-09-01 by
exhaustive grep: both paths build `[ChatMessage(role="user", content=payload.message)]`
(`app/api/routes/chat.py:113` streaming, `:257` non-streaming), and
`ChatService` only forwards what it is given. No conversation history is
assembled anywhere in the request path.

ORQ-37 Block B is chartered to integrate `E-BM25`, whose purpose is recovering
out-of-window evidence from a long conversation history. It therefore has no
substrate to stand on. Building that substrate inside an `E-BM25`-shaped
adapter would bury two platform capabilities — ordered history and tenant-safe
reads — where neither would be reusable nor independently reviewable.

Two constraints shaped the design.

**Historical ordering.** `Message.sequence` (`BigInteger, Identity(always=True)`)
was added by migration `f1e2d3c4b5a6`, a bare `add_column` with no backfill, so
PostgreSQL numbered pre-existing rows in physical heap order. `created_at`
cannot break the tie: `func.now()` is transaction-stable and `/chat` writes both
messages of a turn in one transaction, so they share a timestamp — which is why
ORQ-28 existed.

**Tenant scoping.** ADR-004 §3 deliberately omitted a `tenant_id` filter from
the messages query, conditioning that on a precondition it stated explicitly:
messages are fetched only after `get_conversation` has validated ownership, and
the route is the single call site. It also named the case that would invalidate
the precondition — "if `list_messages_for_conversation` is ever called from a
context where conversation ownership was not pre-validated".

---

## Decision

### 1. A provider-agnostic domain component

`ConversationHistoryPort`, `HistoryMessage`, `AssembledHistory` and
`ConversationHistoryAssembler` live in `app/core/domain/conversation_history.py`,
mirroring `RetrievalPipeline`'s constraints: no DB access, no FastAPI/HTTP
semantics, every dependency injected. `HistoryMessage` carries `sequence`,
`role` and `content` — no `created_at`, because it is not an ordering key and
cannot corroborate order.

### 2. Ownership validation is a port contract, not adapter behaviour

Any `ConversationHistoryPort` implementation must validate that the conversation
is owned by the tenant and raise `ConversationNotFoundError` if not — never
return an empty sequence, which a caller cannot distinguish from an empty
conversation. This is stated in the Protocol docstring so a second
implementation inherits it, rather than inheriting only what
`SqlConversationHistoryAdapter` happens to do.

We are the second caller ADR-004 §3 anticipated. A component consumed off-route
cannot inherit a guarantee held by a route it does not traverse, so the guard
moves inside the component.

### 3. Query-level tenant scoping — amending ADR-004 §3

`Message.tenant_id == tenant_id` is added to the `WHERE` of
`list_messages_for_conversation`. This is redundant defence layered on top of
the ownership guard, never the only line. ORQ-38's T3 measured the affected
rows before shipping it:

```sql
SELECT count(*) FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.tenant_id IS DISTINCT FROM c.tenant_id;
```

Result `0` over the available corpus, so no row disappears from
`GET /conversations/{id}`.

`TraceService.reconstruct_by_request_id` (`app/services/trace.py:88-106`) runs
the same unscoped query and is deliberately **not** changed here — a separate
read path with its own callers and tests. Tenant isolation on message reads is
therefore query-enforced on `ConversationQueryService` and still
caller-dependent on `TraceService`.

### 4. `ConversationNotFoundError` conflates not-found with forbidden

ConversationNotFoundError deliberately conflates not-found with forbidden, inheriting ADR-004 section 2's decision that a cross-tenant response must be indistinguishable from a not-found response.

Do not split it into distinguishable errors: that reopens the existence oracle
ADR-004 closed.

### 5. Ordering is forward-only, and this ORQ does not characterize the rest

Message.sequence is authoritative going forward.

For rows written before migration f1e2d3c4b5a6, no evidence exists today that would allow a defensible chronological order to be reconstructed.

ORQ-38 neither repairs nor classifies historical message order.

Three fresh-context design-review rounds each defeated a different mechanism
for characterizing those rows: a direct `created_at`/`sequence` comparison
(invalid — transaction-stable timestamps), equivalence classes over equal
timestamps (blind to the intra-turn inversion ORQ-28 actually fixed), and an
inferred legacy watermark (unsound in both directions). The work moved to an
unclaimed read-only successor ORQ that is not a prerequisite of ORQ-37.

### 6. Bounds

`conversation_history_max_messages` (20) and `conversation_history_max_chars`
(12 000), both rejecting non-positive values. The message cap applies first,
then the character cap; both drop whole messages from the oldest end.
`truncated` is derived as `total_available > len(messages)` — it means messages
were dropped, nothing more. A single message longer than the character cap is
returned with the cap exceeded rather than yielding a useless empty window.

### 7. Deliberately unwired

Nothing in the request path calls this component. ORQ-37 Block B is its named
consumer.

---

## Consequences

### Positive

- Tenant safety holds by construction on this path, in every branch, with no
  dependency on a future consumer remembering an external guard.
- Two platform capabilities are reusable and independently reviewable instead
  of buried inside a retrieval adapter.
- The forward-only ordering limitation is now recorded where a consumer will
  find it, rather than being discovered at integration.

### Negative / Trade-offs

- Layer 1 costs one extra primary-key lookup per assembly.
- `fetch_ordered` takes no `limit`: it reads the full conversation and bounds
  afterwards, so `total_available` is meaningful. There is no
  `(conversation_id, sequence)` index and none involving `tenant_id`
  (`app/models/message.py:64-66` declares only
  `ix_messages_conversation_id_created_at`), so both the `WHERE` and the
  `ORDER BY` are unsupported. Accepted and carried to ORQ-37 as disclosed debt;
  adding an index was explicitly not authorized here.
- The component ships with no production caller — two unwired modules.
- `fetch_ordered` raises for a conversation row that does not exist yet.
  `/chat` creates that row inside the write transaction
  (`app/api/routes/chat.py:134` / `:258`), so ORQ-37 must skip the call on a
  first turn rather than catch the error.
- The ownership guard makes `SqlConversationHistoryAdapter` depend on
  `ConversationQueryService` rather than being a thin mapper.

---

## Alternatives Considered

### Alternative A: rely on ADR-004's route-level guard

Discarded. ORQ-38's adapter is consumed off-route, so the precondition ADR-004
§3 depends on does not hold. Keeping the guard external would ship a port whose
`tenant_id` parameter is inert — the trap ADR-004 §3 named — into a Protocol
ORQ-37 is chartered to consume.

### Alternative B: return an empty sequence for an unowned conversation

Discarded. Indistinguishable from an empty conversation, so a caller cannot
tell isolation from absence and a regression would be silent.

### Alternative C: characterize historical ordering inside this ORQ

Discarded after three review rounds each defeated a different detection
mechanism. Refining it a fourth time inside a substrate ORQ would have delayed
the substrate for an analysis nobody had yet shown ORQ-37 needs.

### Alternative D: place the adapter in `app/core/providers/`

Discarded. That directory holds implementations of ports over external
providers behind a network boundary. This one composes an existing service over
the app's own database, so it belongs in `app/services/`. The deviation from
the port-implementation convention is deliberate.

---

## Evidence

- ORQ: `.framework/orqs/ORQ-38-conversation-history-substrate/spec.md`
- T3 measurement and closure evidence:
  `.framework/orqs/ORQ-38-conversation-history-substrate/implementation.md`
- Roadmap amendment: commit `aa3c8ef`
- Amends: `docs/adr/004-tenant-scoping-read-endpoints.md` §3 (and §2 for the
  not-found/forbidden conflation)
- Related: ADR-009 (Alembic chain), ORQ-28 (deterministic message ordering)
