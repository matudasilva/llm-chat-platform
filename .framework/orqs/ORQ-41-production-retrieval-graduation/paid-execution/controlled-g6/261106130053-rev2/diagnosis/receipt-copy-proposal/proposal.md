# Implementation update

Operator approved revision2. Exact patch implemented; 279 author P2 checks PASS. See implementation/validation.md and manifest.json. Separate review is pending. The prospective proposal below is retained as historical context; implementation approval is no longer pending.

# C1 window receipt copy optimization proposal

Status: PROPOSAL_READY_FOR_OPERATOR_APPROVAL. Runtime not modified. Recommended diff: revision2/candidate.patch only. The initial patch/evaluation in this directory is superseded: revision2 adds repeated-row identity fallback to preserve deepcopy alias semantics. Do not apply the initial patch.

## Proposed diff

Only app/core/observability/context_evidence.py: introduce one private helper for copying window receipts and use it at window.materialized, window.pack and context.packed (three current deepcopy call sites). The helper clones the list and each row dictionary when all containers are exact built-in types, rows have distinct object identities, keys are exact strings and values are immutable built-in str/int/bool/None. Nested/unexpected types, subclasses or repeated row references retain the original full deepcopy behavior.

All receipt fields, ordering, sequence IDs, occurrence keys, retained prefixes and snapshot structures remain identical. Stage JSON encoding, SHA-256 calculations, hash chaining, byte/item limits, late-write invalidation, locks, generic evidence behavior and final snapshot deepcopy are unchanged. This proposal adds no content/hash cache and removes no stage, receipt or verification. Business functions execute before their observational wrapper exactly as before. No domain/provider/route/persistence/stream code changes.

## Offline sufficiency evidence

revision2/evaluate.py loads the proposed source into a separate temporary module; it never replaces the imported production module or edits app/. It uses eight nonempty histories from the frozen 40-request diagnostic fixture. It compares 48 original/proposed full observation traces exactly (normal packing, prefix truncation, byte cap failure, item cap failure, builder failure and aborted request). Exact snapshot equality includes every stage, field, hash and validity/lifecycle state. Additional alias/fallback checks cover nested receipts, unexpected mutable fields, dictionary subclasses, repeated dictionary references, isolation of record data from mutable state.window, and snapshot mutation isolation: 57 checks total PASS.

P2 evaluation: unshare -rn; env -i, empty HOME, absent provider credentials/config, metadata disabled, empty application dotenv path, socket guard, empty network audit. No API requests, DB queries or external/provider calls; USD 0. The current source hash still equals the baseline hash in revision2/result.json.

Seven rotating-order batch measurements of 2,400 copy operations each: median CPU 242.778 ms with deepcopy versus 66.151 ms with the candidate (72.8% lower for this copy microbenchmark). That is approximately 0.074 ms saved per 48-receipt copy, or 0.221 ms per three copies in this synthetic replay. These are aggregate local copy costs, not request latency or p95. This evidence supports a small equivalent optimization; it does not demonstrate that it will close G6's +5% criterion. The complete request has other CPU costs, and the previous combined paired median CPU delta was 8.514 ms.

## Authorized implementation surface if approved

- app/core/observability/context_evidence.py: the exact revision2 patch, subject to code review.
- tests/experiments/test_orq41_c1_evidence.py (or one isolated sibling): retain counterfactual equivalence and alias/fallback controls as deterministic regressions.
- ORQ-41 diagnostic evidence/handoff: record validation only. No other app/P5 changes.

## Validation and acceptance

Run focused C1 evidence tests under P2 first, then existing C1 remediation/transport/render-dispatch and gate-validation regressions covering JSON/SSE, correlation, failure/cancellation, mutation, hashes and limits. Require exact receipt/serialized-payload equivalence and best-effort preservation. Verify fallback invocation for nested/subclass/aliased rows; no content sharing across mutable containers. If any check fails, do not broaden the patch. Obtain independent review before building a new candidate or any separately authorized timing run. The original controlled G6 FAIL remains unchanged; no paid admission or official G6 rerun is authorized by this proposal.

## Residual risks

Scalar/type scanning adds work and may have negligible net gain on empty or fallback-heavy workloads. The offline histories are representative fixture inputs, not retained full historical state. Allocation/GC/host effects can differ in pinned containers. The helper must remain restricted to the three known window-copy call sites; generic Evidence.snapshot deepcopy remains intact. The scope is small, but performance sufficiency for G6 is unproven.

Operator decision requested: approve or reject this exact bounded observational-only patch and its deterministic regression tests. Approval to prepare this proposal did not authorize editing runtime.
