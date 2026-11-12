# Within-cell crossover execution

DIAGNOSTIC_CROSSOVER_COMPLETE. One execution of the prospectively reviewed plan bcd882d10e1bf57b359135dc7b2eb408c55eed8412dbf717aa6f097f016c4f4b. This is a diagnostic, not an official G6 rerun.

## Integrity and validation

64/64 local requests completed:32 measured and32 mixed combined/empty warmups in16fresh workers. Paired native serialized rewrite/primary payloads and call sequences match.32unique candidate accounting instances passed full worker validation. Exclusive execution-started.json prevents resume/resend; each fresh identity was admitted once. The reviewed source, image, settings, fixture and protocol/analyzer hashes remain fixed. Raw C1 chains are checked by the worker but not separately retained in timing receipts.

51author controls passed in the pinned C1 Python3.13.15 image with network-none/P2; four independent prospective controls passed. Prepared DB/config proof passed32conversations/768messages per arm. Parent-executed final read-only verifier passed32conversations/832messages,768exacthistory messages plus one user/assistant exchange per conversation, unchanged P3/RLS/schema/config. Only64 newly generated message UUIDs per arm were normalized after uniqueness checks for paired business equality. Reviewer attribution is separate from parent SQL execution.

## Prespecified balanced contrasts

For each cell/category, d0 and d1 are the paired C1-minus-C0 preparation durations in opposite-order blocks. The source contrast is(d0+d1)/2. The order contrast is(d_C0-first minus d_C1-first)/2. These descriptive contrasts do not isolate causal effects unless additive/stationary assumptions hold. They are not percentile estimates. Negative source values favor C1.

| Cell | Category | Balanced source wall ms | Balanced source processCPU ms | Order wall contrast ms |
|---|---|---:|---:|---:|
| EN-json | combined | -18.309 | -14.789 | -3.353 |
| EN-json | empty | -11.728 | -10.432 | -12.635 |
| EN-sse | combined | -36.869 | -14.871 | -4.059 |
| EN-sse | empty | -15.421 | -13.404 | 3.453 |
| ES-json | combined | -1.167 | 1.944 | 6.370 |
| ES-json | empty | 9.306 | 8.470 | 9.578 |
| ES-sse | combined | -33.545 | -15.754 | 2.477 |
| ES-sse | empty | -17.352 | -14.869 | 0.242 |

Combined source wall contrasts are negative in all four cells; empty is negative in three and positive in ES JSON. Each contrast contains only two paired measurements of the same business case with fresh conversations, one in each source order. The same businesses also recur across protocols, so these are not32 independent business scenarios.

Across the eight first-order pairs in each stratum, signed wall medians are-19.386ms when C0 runs first and-16.275ms when C1 runs first. Thus the previous sign reversal by source order did not reproduce in this warmed, within-cell crossover. This does not prove that order or host effects disappeared, nor that the old failure was a false positive. Relative performance varies strongly between cells and runs; estimates are small-sample descriptive only.

GC/SQL/SDK interval unions and all raw paired values remain in analysis.json. SQL awaits include driver and scheduling; GC association is process-level. Intervals are clipped and overlap-safe; processCPU includes all threads and cannot be subtracted from wall to invent waiting time. No components were added or subtracted to correct G6 latency. Warmup composition and schedule differ from original formal G6, and this population omits document-only/history-only measured cases, so it cannot certify the full workload or+5% p95 rule.

## Recommendation

The next decision should concern the prospective measurement protocol, rather than another speculative runtime micro-optimization. Propose a minimal formal G6 protocol amendment with representative equal warmups and within-cell source-order balancing, while preserving all original measured case categories/counts, N=100 per arm/cell, p95 calculation, timing endpoint, model/config/resources, full C1 evidence and+5% ceiling. Freeze and independently review any amendment before operator approval and one authorized execution. Retain every prior FAIL; no favorable-run selection, retroactive warmup exclusion or correction of old samples is justified. This report does not implement or authorize that amendment or a new formal gate.

## Scope and commands

Only new isolated crossover controller/worker, focused tests, packet evidence and planning handoff were added; no app, reviewed wait observer, P5, provider/retry/retrieval/SSE/persistence/schema/global-env/model/threshold/accounting change. Commands: controlled_latency_crossover (prepare), --execute <packet> (once); prepared/final readonly verifiers --run <packet>; analyze.py offline. Host uses scrubbed env/unshare-rn and P2 guard; workers use PostgreSQL network-none namespace without published ports and memory-only provider/embedding/rerank stubs. Audit absent/empty, external/provider calls and paid spend zero. No campaign, Notion, commit or deployment. Global Implement/DECISION_FREEZE_PASS and official G6FAIL/paid block remain. Independent execution review is recorded separately.
