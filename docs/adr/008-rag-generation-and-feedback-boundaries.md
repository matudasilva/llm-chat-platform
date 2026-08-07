# ADR-008: RAG Generation and Feedback Boundaries

**Date:** 2026-08-06
**Status:** Accepted
**ORQ reference:** ORQ-25
**Superseded by / Supersedes:** —

---

## Context

ORQ-21 introduced a tenant-isolated RAG corpus, ORQ-23 introduced the retrieval pipeline, and
ORQ-24 made reranking resilient through a provider cascade. Those capabilities remained isolated
from `POST /chat`. ORQ-25 is the first change that consumes retrieval in the authoritative chat
write path, so it must preserve transaction, streaming, provider-abstraction, cache, tenant, and
telemetry invariants while exposing useful source attribution.

The roadmap also asks for lightweight answer feedback and suggested a visible `<think>`
scratchpad. `UsageEvent` is already the one-to-one operational record linked to a successful
assistant message, but it had no feedback fields. Visible reasoning is not required to ground an
answer and would create an unnecessary public reasoning surface.

## Decision

1. Add an independent, inert-by-default `CHAT_RAG_AUGMENTATION_ENABLED` flag. Enabling the
   read-only retrieval endpoint does not enable chat augmentation, and enabling chat augmentation
   does not enable the read-only endpoint.
2. Resolve retrieval through a short-lived RLS application-role session before `POST /chat`
   opens its business transaction or creates its streaming response. Retrieval failure or timeout
   degrades to normal generation with no RAG context.
3. Pass a bounded, provider-neutral source envelope through `ProviderInput.metadata`. A shared
   formatter converts validated metadata into one canonical system message; routes and
   `ChatService` never branch on provider names.
4. Return public source descriptors (`citation`, `document_id`, `chunk_id`, and `rank`) in the
   non-stream response and the existing SSE `done` payload. Chunk content is sent only to the
   provider prompt, never to the public descriptor or telemetry.
5. Bypass the existing Redis response cache whenever chat augmentation is enabled because its key
   does not include corpus or retrieved-source identity.
6. Store `up`/`down` feedback by updating the existing successful assistant `UsageEvent` through
   `PUT /chat/messages/{message_id}/feedback`. The tenant-scoped join hides foreign targets as
   `404`, repeated identical feedback is a true no-op, and ambiguous historical duplicates fail
   closed with `409`. No Conversation or Message is written.
7. Do not request or expose a `<think>` scratchpad. The prompt asks for answer-only output with
   best-effort `[S#]` markers and treats retrieved text as untrusted evidence.

## Consequences

### Positive

- Retrieval network calls cannot extend the business transaction or begin after SSE token
  emission.
- The chat/domain layers remain provider-agnostic and the `ProviderPort` signature remains stable.
- Public citations are deterministic and content-free while the provider still receives bounded
  source text.
- Feedback reuses the existing trace/cost record without adding duplicate events or a second
  write-path prefix.
- Default deployments retain their current behavior until the dedicated flag is enabled.

### Negative / Trade-offs

- Chat augmentation adds pre-generation latency and another short-lived database session when
  enabled.
- Cache is fully bypassed for augmented chat until a corpus-aware cache key exists.
- Inline citation correctness remains model-dependent; structured sources prove which context was
  supplied, not that every generated claim is supported.
- Feedback assumes one successful UsageEvent per assistant message and must reject historical
  ambiguity rather than silently choosing a record.

## Alternatives Considered

### Alternative A: Activate chat RAG with the existing retrieval flag

Rejected because deploying or testing the read-only endpoint would silently change the core write
path. Independent rollout and rollback controls are required.

### Alternative B: Add retrieved chunks directly to the provider contract

Rejected because a RAG-specific signature would contaminate the stable provider abstraction.
`ProviderInput.metadata` already exists for provider-neutral additive context.

### Alternative C: Persist a new feedback event

Rejected because duplicate UsageEvents would distort request cardinality, cost, and trace
analytics. Updating nullable fields on the existing successful event preserves those semantics.

### Alternative D: Expose a visible reasoning scratchpad

Rejected because grounding requires evidence and citations, not public chain-of-thought. The
observable contract is answer-only output plus structured source descriptors.

## Evidence

- `.framework/orqs/ORQ-25-rag-generation/spec.md` — approved design and acceptance criteria.
- `app/core/domain/rag_generation.py` and `app/core/domain/provider_prompt.py` — bounded source
  normalization and provider-neutral prompt materialization.
- `app/api/routes/chat.py` and `app/api/routes/chat_feedback.py` — chat integration and feedback
  boundary.
- `tests/core/test_rag_generation.py`, `tests/api/test_chat_rag_generation.py`, and
  `tests/api/test_chat_feedback.py` — contract evidence.
- `tests/core/test_usage_event_feedback_migration.py` — reversible migration evidence against
  PostgreSQL; implementation validation passed on 2026-08-06.
