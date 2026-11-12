# Controlled G6 execution independent replay

**CONTROLLED_G6_FAIL — independently verified.** No result was replaced, no
request was repeated, and no threshold or implementation was changed by review.

The independent `verifier.py` replays retained rows without calling the production
summarizer. It ran under `unshare -rn env -i`, P2 guard, absent provider credentials
and disabled metadata discovery. No API, SQL, Docker or provider operation was
performed. Only these review artifacts were written.

## Population and integrity

- Frozen plan SHA256:
  `d27e1cdabcd6bfdbf2fc43d22e510522d9c3f0f53db0bea6c14eefb7d940bee6`.
- Result SHA256:
  `a85ce6a66129b379f5d9eddc5fc7734a18a6e10711446dc4fc6286dcb8003a34`.
- All frozen harness/support hashes, approval binding and eight worker receipt
  hashes match current files.
- Eight complete cells contain 105 rows each: **840 requests**, **800 measured**
  and **40 warmups**. No functional failures or missing/duplicate samples.
- Every row matches the frozen order, metadata and deterministic request/
  conversation UUIDs. Each measured cell contains 25 samples per category.
- Timestamps are integer, ordered, and exactly reproduce preparation durations.
  Paired serialized rewrite/primary payload hashes and call counts match.
- All 420 candidate accounting-instance UUIDs are unique; baseline rows have no
  candidate accounting identity. Full raw chains were validated by the reviewed
  worker before accepting rows, but are not retained in these timing receipts;
  this post-run replay does not claim to revalidate their raw contents.
- No network guard audit attempts are recorded; no external calls or spending
  are claimed. The reviewed in-memory transports and isolated topology remain
  the basis for this controlled, credential-free execution, not live-provider
  readiness evidence.

## Independent threshold calculation

Warmups are excluded explicitly. With 100 measured values per arm/cell, nearest
rank p95 is sorted index94. Independent integer comparison is exactly
`candidate_p95 * 100 <= baseline_p95 * 105`. p50, p99 and maximum also match the
published result.

| Cell | C0 p95 (ms) | C1 p95 (ms) | Relative overhead | Result |
|---|---:|---:|---:|---|
| EN JSON | 80.236189 | 88.975023 | +10.891387% | FAIL |
| EN SSE | 70.654420 | 79.399885 | +12.377803% | FAIL |
| ES JSON | 78.821390 | 85.851376 | +8.918881% | FAIL |
| ES SSE | 74.142925 | 81.396829 | +9.783677% | FAIL |

All four cells exceed the approved +5% limit. Driver process exit0 only means
its operations and result publication completed; `CONTROLLED_G6_FAIL` is the
gate disposition. It is not a gate PASS. No paid campaign was started by review.

## Interpretation and next bounded diagnosis

Retain this single run as failed controlled G6 evidence. R=1, fixed balanced arm
order and host jitter remain limitations; they do not excuse or erase the failure.
This stubbed comparison does not measure live-provider absolute bounds or imply
that a paid run would pass.

The next safe diagnostic is offline decomposition of retained preparation values
by category, sample position and cell, together with a static inventory of C1-only
work before the endpoint. Distinguish runtime accounting from harness Capture/SDK
hook bookkeeping: both can contribute within the frozen controlled boundary.
Do not attribute the entire measured difference to one component without evidence.
Any profiling, optimization or new execution requires its own scoped proposal;
do not rerun this population to select a better result or relax the threshold.
