# ADR-020: Admit Global Manual Model Selections

**Date:** 2026-11-23
**Status:** Accepted
**Reference ORQ:** ORQ-43
**Related decisions:** ADR-014, ADR-015, ADR-016, ADR-017 and ADR-018

---

## Context

Clients need an optional per-message choice from a server-managed catalog without supplying arbitrary provider configuration. Selection must be validated before chat dependencies acquire sessions or perform retrieval, and an in-flight request must retain one tenant, catalog entry and settings generation. Existing clients retain their configured routing and technical fallback behavior.

## Decision

We admit an optional opaque `model_id` against a global, startup-validated catalog and capture the entry, tenant and immutable settings generation for the request. The catalog defaults to empty. `GET /models` exposes enabled entries' safe display fields only. Invalid and disabled selections fail with 422 before chat side effects. A selected entry composes one bounded provider behind `ProviderPort` without cross-provider fallback, and bypasses response-cache reads and writes. Omitted or null selection preserves existing routing, fallback and cache eligibility.

This decision creates a narrow exception to the runtime guards in ADR-014, ADR-015 and ADR-016: an explicitly enabled catalog entry may select Vertex only when its separate, default-off gate and settings validate. Global primary and fallback settings and generic factory construction still reject Vertex. ADC acquisition remains lazy. Streaming ownership and the ban on fallback after emission remain unchanged.

Manual routing evidence reports the selected provider/model and known usage. The implementation has no trusted exact-version mapping for manual entries, so final identity, price and cost remain unknown even when an adapter reports a model version. Legacy `UsageEvent` converts unknown token values to zero; it does not preserve unknown usage.

## Consequences

### Positive

- Selection is server-controlled and request-bound; in-flight requests retain their admitted snapshot.
- A selection cannot silently change provider on failure or reuse an inadequately scoped cache entry.

### Negative / trade-offs

- Catalog configuration is startup-only: changes require a restart, and disabling a choice does not revoke already admitted work.
- The conservative evidence policy cannot report a final model or cost for manual selections until a separately trusted mapping exists.
- Catalog allowlisting establishes neither model lifecycle, access, quota, capacity, quality nor price. No entry is enabled by default, and hermetic tests do not establish paid or live readiness.

## Alternatives considered

### Reuse global routing or fallback for manual choices

Rejected because a failure could select a different model and violate the caller's explicit choice.

### Include model identity in the existing response-cache key

Rejected until identity and cache admission are separately established for the complete execution configuration.

## Rollback

Disable the Vertex gate or remove/disable entries in a validated configuration and restart. Already admitted requests finish with their captured generation. Revert the implementation if necessary; the global Vertex primary/fallback guards remain in place.

## Evidence

- `.framework/orqs/ORQ-43-manual-model-catalog/design/t1-design.md`
- `tests/api/test_orq43_admission.py`, `tests/api/test_orq43_chat_integration.py` and the catalog/provider tests exercise hermetic paths without paid calls.
