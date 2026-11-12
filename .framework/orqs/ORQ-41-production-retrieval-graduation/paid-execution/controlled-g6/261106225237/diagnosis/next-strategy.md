# Proposed next C1 performance strategy

Status: EVALUATED_REJECTED_FOR_G6_REMEDIATION. See count-evaluation/report.md. The operator-authorized offline evaluation passed 68 equivalence checks but showed only about 0.04 ms median savings for history/combined. No runtime change or new API request execution.

The approved G6 ceiling remains candidate p95 <= baseline p95 * 1.05 in every cell. The latest optimized candidate exceeds that ceiling by approximately 2.987 ms (EN JSON), 0.135 ms (EN SSE), 2.424 ms (ES JSON), and 3.652 ms (ES SSE). These are observed percentile gaps, not per-request costs or causal optimization targets.

## Selected hypothesis

Evaluate the complete Evidence._add registration path, beginning with recursive item counting. Every stage traverses its data to count nested list members, serializes the record canonically and hashes it. The counter currently invokes itself for scalar fields that contribute zero. Large receipt arrays repeat that work across stages. This is a concrete candidate for reducing Python calls while preserving the exact accounting result. It is not yet a measured bottleneck.

Prefer an exact built-in-container fast path for counting, with original behavior retained for unsupported shapes. Keep canonical serialization, SHA-256, byte/item caps, locks, record order, content-free evidence and best-effort behavior unchanged. Do not remove records, cache plaintext, weaken correlation, defer work beyond the measured boundary or subtract estimated costs from observed latency. Serializer replacement and new dependencies are outside this proposal.

## Bounded evaluation before implementation

1. Reuse the frozen offline document/history/combined/empty workload construction. Retain full C1 observations, including native render/delivery receipts. Create representative stage inputs locally; identify reconstruction limitations explicitly.
2. Compare current and proposed counting implementations in a temporary counterfactual module, outside app/. Run the complete observer workload with aggregate process CPU and wall clocks only, rotated arm order and retained warmups/raw batches. Do not install per-function timers, contact a database/API/provider, or rerun G6.
3. Require exact counts and full observation-chain equality: serialized bytes, hashes, records, size/items, cap boundaries, invalidation, exceptions and functional outcomes. Include empty/nested inputs, aliases, subclasses and observation failure. Preserve fallback behavior when the fast path cannot prove equivalence.
4. Evaluate savings at the complete-observer workload level. A tiny helper-only improvement is insufficient justification for another image or gate run. The observed gaps require savings on a millisecond scale; an offline saving still cannot certify p95 or G6 PASS.
5. Only if correctness and repeatable material savings support it, submit the exact small patch and evidence for approval and independent review. Otherwise reject this hypothesis and retain the current candidate and failure.

Likely evaluation artifacts: an isolated script and result/report under this diagnosis directory. A later approved runtime patch would affect only app/core/observability/context_evidence.py plus focused tests. No change is approved by this document.

## Alternatives evaluated

- Another identical G6 run: provides no new remediation and risks favorable-run selection; reject.
- More receipt-copy or duplicate UTF-8 tuning: existing measurements did not establish enough benefit; deprioritize.
- Move hashing/validation outside the timing interval: changes attribution without proving lower complete-workload cost; reject as a strategy for passing this gate.
- Lower or relax the threshold: governance/design change, not remediation; outside scope.

P2, local stubs, zero external spend and the paid-admission block remain mandatory. Existing G6 failure, original evidence and global Implement / DECISION_FREEZE_PASS remain unchanged.
