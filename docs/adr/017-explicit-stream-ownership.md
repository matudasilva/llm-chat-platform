# ADR-017: Explicit Stream Ownership Across Chat Layers

**Date:** 2026-11-17

**Status:** Accepted - bounded T14 implementation only

**ORQ reference:** ORQ-42, T14
**Supersedes / Amends:** Complements ADR-014, ADR-015 and ADR-016

## Context

Acquired streaming sessions and eager consumer tasks crossed adapter,
resilience, service and route boundaries. Closing an unstarted async generator
did not release resources it had not yet begun to own. Cancellation or client
disconnect could therefore leave an upstream consumer active. The existing
ProviderPort, atomic `/chat` write path, SSE protocol and pre-emission-only
fallback remain constraints.

## Decision

Use explicit closeable ownership of acquired stream iterators and drivers at
the adapter, resilience and service boundaries. Transfer ownership immediately
after acquisition and close it on cancellation or route finalization. Retain and
observe asynchronous cleanup that outlives the route's bounded wait. Isolate
individual result waiters and terminate waiters when their session is closed.
Preserve the tracing context across pulls and emit best-effort evidence for the
actual outcome. OpenAI and Bedrock own their stream resources; injected shared
clients are not closed. Keep ProviderPort signatures, SSE framing, tenant
isolation, transaction boundaries and fallback rules unchanged.

## Consequences

- Closing before the first pull and cancellation during fallback transfer can
  release resources already acquired by these layers.
- A cleanup that never returns can hold normal EOF. Route cancellation waits a
  bounded interval and retains the cleanup task for observation. Cancellation
  of an asyncio task cannot prove that a synchronous SDK worker thread or
  upstream generation has stopped.
- Hermetic tests establish covered behavior only, not live account readiness,
  production activation, provider availability or model quality.

## Alternatives Considered

- Rely on async-generator `finally`: rejected because an unstarted generator's
  body never acquires responsibility for resources already obtained elsewhere.
- Change the public provider contract: deferred because an owned iterator can
  implement the existing async iterator interface with additive `aclose`.

## Evidence

The reviewed design is recorded locally under ORQ-42 T14. The owner joint
hermetic regression passed 231 tests with warnings treated as errors. A fresh
native Terra implementation review passed the bounded change with 98 focused
tests under default warning handling; same-provider independence is reduced.
No live inference was performed.
