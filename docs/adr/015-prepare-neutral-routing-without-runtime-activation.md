# ADR-015: Prepare Neutral Routing Without Runtime Activation

**Date:** 2026-11-17

**Status:** Accepted - bounded T12 preparation only

**ORQ reference:** ORQ-42, T12 preparation
**Supersedes / Amends:** None

## Context

The routing objective is a small reversible deterministic policy, with static
behavior by default and at most one objectively justified alternative. The
legacy heuristic uses last-message length and an estimated token proxy; those
signals do not establish task difficulty or full-request capacity. History,
retrieved conversation evidence and document RAG are already assembled through
ProviderInput and the shared canonical formatter.

ADR-014 prepared Vertex without enabling runtime selection. The current cache
lookup still precedes routing, and cross-layer stream ownership remains later
work. A policy mode must not become selectable before those integration gates.
There are no approved candidate configurations, input/output capacity
certifications or bounded quality results for an alternative. KEEP_STATIC
therefore remains the operational disposition.

## Decision

1. Prepare a neutral seam that passes the same ProviderInput to routing
   observation and actual provider execution. Observe the complete canonical
   envelope through a shared preview without C1 render/mapping side effects.
   Preserve provider-dispatch instrumentation, prompt content/order and the
   legacy static/heuristic behavior.
2. Represent aggregate request observations independently of provider APIs.
   Character/byte counts and fingerprints are not token counts, difficulty,
   quality or certification. Keep unknown output requirements unknown; do not
   infer an effective provider budget from an absent request control.
3. Test the small deterministic policy through direct construction only.
   Disabled behavior delegates exactly to the existing static policy. Synthetic
   enabled-rule tests require request/transport/output/destination-bound
   eligibility and scoped quality evidence before selecting the sole
   capacity-based alternative. Missing or mismatched evidence fails closed.
   No application evidence producer or certification service is introduced.
4. Keep the new active/shadow policy mode rejected by Settings and direct
   composition. Keep the existing Vertex primary/fallback and factory guards.
   Add no runtime enable switch, cache change, provider API call, telemetry
   producer, stream-ownership change or model selection in this preparation.
5. Keep initial selection distinct from technical fallback. Disabled static
   routing preserves its current fallback. The isolated new rule cannot
   attach a default destination that was rejected for capacity, or reuse
   capacity-condition quality evidence to justify a different fallback scope.

This decision and its preparatory code belong in the same eventual PR. It
does not authorize subsequent integration, measurement, activation, commits
or ORQ closure.

## Consequences

### Positive

- The neutral observation seam includes history and rendered evidence without
  changing ProviderPort, prompt templates or the persistence boundary.
- Static rollback and the dormant rule can be tested without provider access.
- Runtime selection cannot bypass missing cache and cancellation safeguards.
- Unknown or stale evidence cannot silently become an admissibility claim.

### Trade-offs

- The new policy remains unavailable to application requests. Synthetic rule
  tests establish mechanics, not quality, trigger reachability or useful routing.
- ProviderInput is shallowly frozen: observation must not mutate caller-owned
  messages/metadata. Its fingerprint is a snapshot, not a concurrency lock.
- The existing stream-to-run compatibility fallback retains its second
  resolution. This preparation does not refactor that behavior or establish
  cross-layer cancellation readiness.
- Real candidate configuration/capacity/quality evidence and safe runtime
  integration remain necessary before any alternative is considered eligible.

## Alternatives Considered

### Repurpose the length-based heuristic

Rejected: a short final message can accompany substantial history or RAG, and
neither length nor estimated tokens establishes difficulty or certified capacity.

### Enable the mode now and repair cache or ownership later

Rejected: cache can return before the new policy runs. The integration gates
must precede activation, as documented in ADR-014 and the reviewed design.

### Build tokenization, quality scoring or an evidence registry now

Deferred: no chosen configuration or demonstrated reachable trigger justifies
that infrastructure. KEEP_STATIC is an acceptable outcome. No learned router,
gateway or paid comparison is introduced.

## Evidence

- Related decisions: ADR-008, ADR-011, ADR-012, ADR-013 and ADR-014.
- Reviewed local contract: ORQ-42 T9 design and bounded T12 preparation addendum;
  a fresh native Terra design review approved T12 after evidence-binding
  clarification. Same-provider independence is reduced.
- Implementation: `app/core/domain/chat_service.py`,
  `app/core/domain/provider_prompt.py`, `app/services/routing_signals.py`,
  routing types/the standalone deterministic policy, and direct composition
  guards in `app/core/domain/provider_factory.py`.
- The final joint hermetic regression passed 271 tests with warnings treated
  as errors. It covers routing, prompt/service contracts, existing Vertex
  preparation, SSE, tenant, transaction/rollback and cache behavior.
- A fresh native Terra implementation review approved only this bounded T12
  preparation; its final R2 independently passed 112 tests and preserves the
  earlier review as history. Exact commands, file hashes and resolved findings
  are recorded in the local ORQ implementation evidence. Same-provider review
  independence is reduced; no production inference or quality claim follows.
