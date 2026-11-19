# ADR-014: Prepare Vertex Generation Behind Disabled Runtime Selection

**Date:** 2026-11-17

**Status:** Accepted - isolated preparation only

**ORQ reference:** ORQ-42, isolated T10-T11 subdelivery
**Supersedes / Amends:** None

## Context

The routing plan now includes Bedrock and Vertex as initial generation candidates,
while retaining static routing and the existing OpenAI integration. The GCP
reranker is a separate capability and does not supply a chat-generation contract.
ORQ-42's approved T9 design requires independent authentication/configuration,
incremental streaming, cache protection and cross-layer cancellation ownership.

The currently authorized implementation is narrower: T10-T11 may prepare and
hermetically test the adapter and its authentication/configuration only. Shared
cache, routing and stream-ownership integration remain later work. `/chat` reads
cache before resolving its provider, so returning DisabledProvider from the
factory alone would not prevent an incorrectly configured Vertex request from
receiving an old cache entry.

## Decision

1. Add independent, unset-by-default Vertex generation configuration. Keep
   `vertex` outside the allowed runtime primary/fallback selection set, including
   configurations with otherwise complete Vertex values. Direct factory access
   to Vertex also returns DisabledProvider. Introduce no enable switch in this
   preparatory subdelivery.
2. Implement text generation and a genuinely incremental, explicitly closeable
   Vertex stream behind the unchanged ProviderPort. Construct it directly in
   hermetic tests with fake tokens and HTTP transport. Do not wire it into live
   request execution, routing heuristics or fallback.
3. Use the existing HTTPX transport and a pinned `google-auth[requests]` dependency
   for lazy ADC discovery and refresh. Load local ADC files or attached identity
   without implicit Cloud SDK project discovery; reject executable credential
   sources. Keep project/location/model independent
   of reranker settings and credential-inferred defaults. No credential discovery
   or refresh occurs at startup or factory construction; model selection and
   account/IAM validation remain separately authorized.
4. Preserve provider-normalized errors, explicit usage missingness, bounded
   pre-emission retries and adapter-owned stream cleanup. Adapter tests do not
   establish route/service/resilience cancellation, tenant or persistence
   readiness for Vertex. Those later gates remain mandatory before runtime use.

This decision belongs in the same eventual PR as the preparatory code. It does
not authorize a separate deployment, paid measurement, model or budget choice,
ORQ closure or immediate runtime integration.

## Consequences

### Positive

- ProviderPort and the current operational provider selection remain unchanged.
- The new dependency implements ADC identity handling instead of duplicating
  service-account signing, metadata-server discovery or federation in application
  code.
- Contract, authentication and streaming errors can be exercised without live
  credentials, API costs or changes to `/chat`.
- Rejecting runtime selection before request handling protects the current cache
  boundary while the later integration work is pending.

### Trade-offs

- Vertex cannot yet serve application requests, even with complete passive
  settings; this is intentional preparation, not production readiness.
- The auth library adds a runtime dependency to pin and maintain, though its
  credential use remains lazy and disabled from live routing in this delivery.
- Live availability, quality, latency, billing and complete-stream disconnect
  behavior remain unmeasured. Hermetic tests cannot remove those limitations.
- The public generic ADC file loader emits a deprecation warning and reopens
  the validated file. This preparation assumes trusted deployment-controlled
  credential files that are not replaced concurrently. The file-loader test
  filters only that specific library warning. A timed-out refresh worker cannot
  be forcibly stopped; callers share its work until completion.

## Alternatives Considered

### Reuse the reranker's credential helper

Rejected: its authorized-user-specific refresh path is not the independent ADC
contract required for generation and deployment identities.

### Enable the new factory destination immediately

Rejected: it would expose Vertex before cache identity/bypass and cross-layer
stream ownership were implemented and verified. A disabled factory by itself
cannot protect a cache lookup that happens earlier.

### Add a full Google generation SDK or a gateway

Deferred: the existing async HTTP transport covers the bounded text contract.
A new gateway is outside scope; a full SDK is not necessary for this subdelivery.

## Evidence and Sources

- Implementation: `app/core/providers/google_adc.py`,
  `app/core/providers/vertex_provider.py`, passive settings and disabled factory
  guard. Focused contract/auth/configuration tests accompany these changes.
- [ADC discovery](https://docs.cloud.google.com/docs/authentication/application-default-credentials),
  [generation API](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/inference),
  [endpoint locations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/locations),
  [pinned authentication library](https://pypi.org/project/google-auth/2.62.2/).
- Joint hermetic regression: 133 tests passed with warnings treated as errors,
  covering the new auth/configuration/adapter tests and existing settings,
  factory, routing, resilience, RAG payload and retry tests. The specific ADC
  loader warning is filtered only by its file-loader test.
- A fresh Terra reviewer approved this isolated, runtime-disabled subdelivery
  and independently ran 78 focused tests. The native review has reduced
  same-provider independence. Exact commands, file hashes and resolved findings
  are recorded in the local ORQ implementation evidence; no paid or production
  result is implied.
