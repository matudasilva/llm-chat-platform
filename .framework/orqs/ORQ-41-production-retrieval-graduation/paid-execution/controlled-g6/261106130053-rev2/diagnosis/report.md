# Controlled G6 offline diagnosis

Status: **DIAGNOSIS_COMPLETE_CAUSAL_ATTRIBUTION_NOT_YET_ESTABLISHED**.
The independently verified CONTROLLED_G6_FAIL remains unchanged. No source/gate/threshold edit, new request, network call or paid spend was performed for this diagnosis.

## Confirmed observations

- All840 original requests completed functionally;400 measured identities have both C0/C1 observations, plus40 excluded warmup requests. Serialized native payload/call-count parity holds.
- C1 is slower in344/400 measured identity pairs: EN JSON89/100, EN SSE95/100, ES JSON84/100, ES SSE76/100. Arms ran in different processes, not simultaneously; these are observed paired-input deltas, not paired causal treatment estimates.
- Aggregate p95 increments remain10.89%,12.38%,8.92%,9.78% against the fixed+5% gate.
- Descriptive category deltas show broader differences, especially history/combined. Median observed pair deltas are history5.81–8.59ms and combined5.13–11.67ms; document3.20–5.54ms; empty ranges-0.26–3.52ms. These posthoc strata do not redefine the gate.
- Top-six p95/max tails predominantly contain document/combined cases, but the two arms'95th samples need not be the same case. Do not replace a ratio of approved quantiles with a median pair delta or a weighted combination of category quantiles.
- Both fixed arm orders include failures, so the result is not explained solely by a rule that the second arm is slower. Repeat-position medians also vary; host/DB/GC scheduling contributions cannot be quantified from these receipts.

## Confirmed interval asymmetry

The worker clock stops on entry to the primary serialized SDK HTTP-send callback, before calling original capture.sent. Therefore the primary Capture.sent bookkeeping is OUTSIDE that request's preparation interval and cannot directly explain its preparation measurement. Candidate snapshot/hash-chain validation and recorder retention cleanup are also after the timed interval; later-request scheduling effects are not ruled out.

Before that endpoint, the candidate executes:

1. Runtime C1 observations: window/document/materialization/prompt mapping, locked Evidence.add, recursive item counting, canonical JSON encoding and SHA-256 chaining (app/core/observability/context_evidence.py and its domain callsites).
2. Candidate-specific harness invocation scopes: ScopedProvider.scope enters application_attempts and c1.invocation. application_attempts creates/registers/removes logging handlers for provider messages (transports.py and capture.py).
3. Candidate SDK attempt hook before signing; no equivalent attempt hook is installed for baseline Tape.
4. Rewrite Capture.sent BEFORE primary dispatch: JSON parsing, rendered message reconstruction/hashes, independent capture copies, and transport.dispatched observation. Baseline Tape.sent retains raw bytes/hash/identity only. Both the independent-capture bookkeeping and actual observation work are currently inside the preparation interval for rewrite.

Those are code facts, not measured per-function cost. Some are legitimate candidate accounting, while others belong to the independent test capture. The original acceptance described the timing method, but a failed comparison cannot establish which component caused it. Payload equality excludes a changed generation input, not CPU/locking/scheduling overhead.

## What is not established

No per-function CPU/wall profile or channel interval tape was retained. Existing ingress/primary timestamps cannot partition runtime accounting, test-only capture, SQL wait, SDK/thread scheduling or host jitter. There is no defensible exact causal percentage or minimal runtime fix yet. In particular, do not subtract an assumed Capture cost from the p95 or erase the original FAIL.

## Next bounded diagnostic proposal

See profiling-proposal.md: a separate free instrumented run with fresh fixtures, no modification to app/P5/thresholds and no replacement gate result. Only after measured attribution should a minimal harness correction or runtime optimization be proposed and independently reviewed.
