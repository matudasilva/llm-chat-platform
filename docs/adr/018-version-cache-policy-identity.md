# ADR-018: Version Cache Identity for Routing Policy

**Date:** 2026-11-17

**Status:** Accepted - bounded initial-selection isolation only

**ORQ reference:** ORQ-42
**Supersedes / Amends:** Amends ADR-016 cache-key format decision

## Context

The existing cache key omitted the routing policy and heuristic thresholds.
Entries created under static and heuristic routing could therefore collide.
The T13 request configuration binding protects in-flight admission but does not
establish the provenance of previously stored keys.

## Decision

Version the cache fingerprint and include the policy, its heuristic thresholds,
nonsecret configured primary availability and Bedrock region in the shared cache
configuration used by key construction and request binding. Preserve tenant
namespace and existing admission/bypass and transaction boundaries. Old keys
are not read by the new fingerprint and expire under their existing TTL; no
Redis deletion or migration is required. No credential value is stored or
hashed as part of this decision.

## Consequences

- Policy and threshold changes no longer reuse the same versioned cache key;
  the first request under the new key is a cold miss.
- The key does not certify account identity, live health, retry or timeout
  behavior, or whether a stored result followed technical fallback. Those remain
  limitations; in-flight dispatched Redis operations cannot be revoked.
- Existing character limits, provider selection, public contracts, persistence
  and streaming are unchanged.

## Alternatives Considered

Keeping existing keys was rejected because their policy provenance is unknown.
Flushing Redis was rejected because a new fingerprint isolates old entries
without destructive operational work. A general cache redesign is outside this
bounded correction.

## Evidence

The owner joint hermetic regression passed 99 tests with warnings treated as
errors. Fresh native Terra implementation review approved the bounded isolation
with 47 focused tests passed under `-W error`; same-provider independence is
reduced. This decision introduces no live inference, model approval or runtime
activation.
