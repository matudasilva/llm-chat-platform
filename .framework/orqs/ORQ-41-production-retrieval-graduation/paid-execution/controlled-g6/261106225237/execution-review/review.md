# Optimized-candidate controlled G6 execution independent review

**CONTROLLED_G6_FAIL — independently replayed and verified.**
Plan SHA256: `cdc785a3ccfb9538882d66f327e71c978ebc85e910cf2a0fa68e21ca6853fbf7`.
Result SHA256: `a6a2cdd17d57529d501880d9a145fc77bfef0ed5dc3119d8ef40c4ade58e8fa8`.

## Population, bindings and evidence

Independent verifier.py replayed all eight retained worker receipts under P2,
without using the production summarizer. Plan/preflight review, frozen harness/
support hashes and every worker/result hash match. The prepared-data receipt is
bound to the same plan and actual per-arm config hashes:420 conversations and
9600 messages per arm, exact fixture content/UUID/sequence, P3/RLS/schema/business
parity and normalized config equality. That read-only DB verification was executed
by the parent, not this reviewer. No post-run SQL or Docker operation was performed.

The rows contain exactly840 successful functional requests:800 measured and40
warmups. Each of eight arm/cells has100 measured and5 warmup rows, with25 measured
rows in each document/history/combined/empty category. Every row matches the
prospective order, metadata and deterministic request/conversation UUIDs. Each
arm has420 unique sample, request and conversation identities; paired arms share
the intended inputs. Timestamps are integer and strictly ordered across the fixed
cell sequence; preparation durations reproduce exactly.

One prospective attempt per sample is frozen. All840 rows contain exactly one
rewrite and one primary native transport send:1680 local memory-only sends total.
Their serialized hashes/call sequences match between paired arms, including
warmups. All420 candidate accounting-instance UUIDs are canonical and unique;
baseline rows do not pretend to contain candidate accounting. The reviewed worker
required valid/closed/correlated hash-chained contexts and application/SDK attempt1
before accepting candidate rows. Raw chains and attempt metadata are not retained
in these timing receipts, so this review does not claim separate raw replay of
those internals. No request or diagnostic rerun was issued by the reviewer.

## Exact threshold replay

Warmups were excluded explicitly. For100 measured observations, nearest-rank p95
is sorted index94; p50, p99 and maxima also match. The independent decision uses
integer arithmetic exactly: `candidate_p95 * 100 <= baseline_p95 * 105`.

| Cell | C0 p95 (ms) | C1 p95 (ms) | Overhead | Decision |
|---|---:|---:|---:|---|
| EN JSON | 75.138562 | 81.882634 | +8.975514% | FAIL |
| EN SSE | 73.304663 | 77.105101 | +5.184442% | FAIL |
| ES JSON | 79.389852 | 85.783142 | +8.053032% | FAIL |
| ES SSE | 70.150033 | 77.309276 | +10.205616% | FAIL |

All four exceed the approved+5% ceiling, including EN SSE. No rounding tolerance,
successful-only denominator change, sample replacement, threshold relaxation or
corrected p95 was applied. A controller exit0 means successful result publication,
not gate PASS. Retain this failed run and all earlier evidence unchanged.

## P2, cost and limits

No external-network attempts are recorded: the configured audit file is absent/
empty. Frozen guard/config and reviewed worker topology require kernel isolation,
scrubbed credentials, local endpoints and memory native generation transports.
Worker/result claims of zero external/provider calls and USD0 external campaign
spend are consistent with that mechanism; local adapter sends are not billed
provider calls. No live/provider network test was performed by this reviewer.

R=1, fixed cell/arm order, host jitter and stubbed integrations remain limitations.
This replay certifies the observed controlled FAIL, not a universal SLA, live
absolute latency/cost bound or an isolated causal optimization effect. No raw
full-response, task scheduling or per-function profile is reconstructed from the
preparation timestamps. Paid admission remains blocked. Only execution-review
artifacts were added; no source or planning-status file was modified.
