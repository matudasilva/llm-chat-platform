# ADR-016: Bind Cache Admission and Routing Evidence to the Executed Request

**Date:** 2026-11-17

**Status:** Accepted - bounded T13 implementation only

**ORQ reference:** ORQ-42, T13
**Supersedes / Amends:** Extends ADR-008/013 cache admission; no activation of ADR-014/015 preparation

**Subsequent amendment:** [ADR-018](018-version-cache-policy-identity.md)
versions the cache fingerprint for policy isolation. This record describes the
original T13 decision and its then-unchanged key format. Account identity,
dynamic availability, timeouts, retries and technical fallback outcomes are not
fully represented by the later cache identity.

## Context

The deterministic policy and Vertex adapter remain unavailable to runtime
selection. Their later integration needs cache protection before routing and
evidence that distinguishes initial selection, actual generation and technical
fallback. Existing response-cache keys do not cover the new mode or Vertex
configuration. Logs based only on LogRecord extras are not serialized by the
current root formatter, and some routing/service/resilience logs can throw.

Cache lookup occurs before generation. Reading mutable configuration separately
at lookup, provider resolution and write can mix configurations across awaits.
Endpoint comparisons alone cannot prove which configuration generated a result.
Cached original usage also must not be presented as a new generation's tokens.

## Decision

1. Bind application ChatService composition to one private deep request snapshot
   of Settings. Use it for resolver/policy, context builder, timeout and both
   provider constructions. Inject a derived opaque execution configuration ID;
   domain orchestration learns no provider-specific settings.
2. Centralize configuration-based cache bypass outside routes/domain services.
   Preserve RAG/EBM25 precedence and streaming bypass; also bypass the dormant
   deterministic mode and Vertex primary/fallback configuration. Keep all
   existing Settings and direct composition rejection gates.
3. Retain initial cache scope and require a matching bound service and current
   scope before lookup, after Redis returns a hit, when scheduling a write and
   immediately before dispatching the post-commit write. Discard stale hits and
   bypass unbound services. Keep key/payload formats unchanged. This guarantees
   write admission, not revocation of Redis I/O already dispatched.
4. On an accepted hit, preserve response/source identity but expose no original
   token counts as current inference usage. The existing UsageEvent writer and
   schema remain unchanged. Emit explicit non-inference cache-hit evidence;
   do not fabricate a current selection, fallback or generation cost.
5. Retain selected decision and optional request-local execution state through
   generation. Mark fallback at its actual dispatch boundary, including failure,
   rather than infer it from differing names. Emit one terminal generation
   record through existing service paths without changing stream ownership.
6. Emit bounded allowlisted JSON in the log message and contain ordinary
   formatting/clock/estimation/sink failures, including touched legacy routing,
   service and resilience logs. Preserve cancellation and original errors.
   Log no prompt, answer, raw metadata, exception text, credential or fingerprint
   in the new evidence.
7. Preserve missingness. Successful final-generation usage may use the existing
   dated per-model price snapshot for an explicitly scoped final-generation
   estimate. Failed-attempt/request-total charges remain unknown; cached tokens
   and lower cost do not establish inference or energy consumption.
8. Treat provider-reported final identity as trusted only when its provider/model
   pair exactly matches the selected or configured fallback pair. An injected
   provider without a routing decision, or an unrecognized model alias, produces
   null final identity and no final-generation cost estimate. This narrow check
   does not introduce alias resolution or a model registry; configured values
   are still trusted identifiers.

This bounded implementation remains in the same eventual PR as this ADR.
It does not enable a route, choose a model, authorize measurement or complete
the later streaming/quality/invariant gates.

## Consequences

### Positive

- In-flight configuration changes cannot label one configuration's generated
  output with another configuration's admitted cache key.
- Cache reuse and actual generation have distinct evidence and usage meaning.
- Selected/final model and explicit generation fallback remain distinguishable,
  including same-label destinations and missing outcomes.
- Evidence failure cannot become a routing or generation failure.

### Trade-offs

- Unbound injected services bypass caching until explicitly composed with a
  captured configuration identity; tests must model this boundary honestly.
- Matching snapshots do not repair historical entries or existing static-key
  omissions, nor certify legacy heuristic caching or account constraints.
- The legacy durable usage schema has no cache flag and still collapses some
  live missing counters to zero. This increment changes neither schema nor
  historical rows; new routing evidence retains explicit missingness.
- Logging is best-effort and not a billing ledger. Service elapsed time includes
  retries/fallback and stream-consumer time; provider latency is separate.
- Final identity and cost can be absent for valid direct-injected providers or
  provider aliases that do not exactly match the trusted configured pair. Cache
  hit evidence omits cached source identity entirely.
- T14 stream-ownership limitations remain. No outcome is invented for an
  unstarted abandoned iterator, and no production readiness is claimed.

## Alternatives Considered

### Expand the cache key for the new routing table

Deferred: conservative bypass is sufficient for this initial bounded policy.
A new key design/migration is unnecessary while activation remains blocked.

### Compare only mutable configuration at write time

Rejected: it loses the initial bypass decision and cannot bind actual generation
through configuration changes. The request snapshot establishes that binding.

### Infer fallback from selected/final provider names

Rejected: fallback may use identical labels, and failures have no final result.
Request-local state records actual dispatch without a global correlation map.

### Introduce a telemetry store, gateway or new stream wrapper

Rejected: existing boundaries support additive evidence without a new write-path,
dependency, background producer or stream-ownership change.

## Evidence

- Related decisions: ADR-008, ADR-013, ADR-014 and ADR-015.
- Fresh native Terra T13 design R2 approved configuration binding and service
  logging containment after R1 findings; same-provider independence is reduced.
- The owner joint hermetic regression run passed 319 tests under `-W error`.
  A fresh native Terra T13 implementation review approved the bounded cache and
  evidence change after a numeric-estimator guard was added for untrusted final
  identities; its focused run passed 57 tests. Independence is reduced because
  review used the operator-selected native Terra path. The review binds the
  implementation files by hash in
  `.framework/orqs/ORQ-42-routing-evidence-dataset/execution-review/t13-terra-review-r2.md`.
  No live inference is implied.
