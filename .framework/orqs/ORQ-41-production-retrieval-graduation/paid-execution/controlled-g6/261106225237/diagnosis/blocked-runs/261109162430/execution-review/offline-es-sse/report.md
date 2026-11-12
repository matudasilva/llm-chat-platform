# Offline ES-SSE analysis: retrieval interval localized; root cause unresolved

**OFFLINE_ES_SSE_ANALYSIS_COMPLETE_CAUSE_UNRESOLVED**, 2026-11-09.
The operator's "dale" approved offline analysis of retained packet261109162430.
No request, new performance sample, service startup or source change occurred.
The complete calibration remains **AA_CALIBRATION_FAIL**; this analysis cannot
replace its metric, remove samples or unblock formal G6/paid admission.

## Evidence and method

The immutable plan/result and distinct execution review bind all 32 workers and
observations. inputs.json hashes 69 inputs; analysis.json, requests.csv and
paired-deltas.json retain every request, phase/category/block and paired timing.
Warmups stay excluded from primary P95. Supplemental partitions below are
descriptive, selected after seeing the FAIL, not new acceptance tests.

Existing collector logs were copied from the stopped retained collector only.
Identity/image/stopped state match the prior cleanup receipt. No services were
started and no new OTLP payload was sent. The raw log contains 7,920 spans and
1,440 unique request roots, all matched to the original accounting_instance_id
through request.instance_id, then checked against request.correlation_id.
Pairing by inbound UUID alone would be ambiguous across the two arms; it was
not used. Every root has its unique expected direct-child stages, with ordered
valid timestamps and no Error status or missing request trace.

All original inputs remained unchanged. A clean scratch copy reproduced all four
derived files byte-for-byte under P2; reproduction.json records exact hashes.
All 500 protected source/test/global-env files remain unchanged. No pytest,
application validation or new benchmark was run.

## What produces the failing P95

Original pooled ES-SSE P95: c0 35.747604 ms; c1 38.757704 ms, symmetric 8.420424%.
All 25 measured cases in each category remain included. All six c1 samples at
or above its P95 belong to combined. They span all four blocks and three
business cases: combined-01, combined-02 and combined-04.
Three ran first and three second. This is not one isolated maximum or one worker.
Indeed c0's maximum (41.704709 ms) exceeds c1's maximum (40.714379 ms), while its
P95 is lower. The 100-row order statistic depends on the upper distribution.

At c0 P95 * 1.05 = 37.5349842 ms, c1 has six rows above the bound and c0 three.
No counterfactual removal/replacement is used; the FAIL remains.

| ES-SSE block | First arm | c0 block P95 ms | c1 block P95 ms |
|---|---|---:|---:|
| 0 | c1 | 35.6512 | 34.5049 |
| 1 | c0 | 35.7476 | 34.5183 |
| 2 | c0 | 37.4311 | 38.7577 |
| 3 | c1 | 34.8476 | 39.2314 |

These block P95s are descriptive only; they are never averaged into acceptance.
The slower label changes across the first/last two blocks. The last two have
opposite first/second order, so a first/second-only explanation is insufficient.

| ES-SSE category (25 measured/arm) | c0 preparation median ms | c1 median ms |
|---|---:|---:|
| document | 24.0805 | 24.9569 |
| history | 8.5885 | 9.5069 |
| combined | 33.7073 | 33.0659 |
| empty | 6.8928 | 7.1692 |

The combined median is slightly lower in c1 despite its higher upper tail.
Across all 25 paired combined samples, preparation difference has median
-0.2258 ms and mean +0.3307 ms. This is not evidence of a uniform +8.42% cost.
Native rewrite/primary payloads match across arms; all five occurrences of
each combined business case have one identical primary and rewrite hash per arm.
No changed request/prompt composition was found to explain the difference.

## Existing traces locate the slow interval

| c1 tail sample | Case | Preparation ms | rag.retrieve ms |
|---|---|---:|---:|
| block1 / 9 | combined-04 | 40.7144 | 31.1872 |
| block2 / 16 | combined-02 | 40.6309 | 31.7590 |
| block3 / 19 | combined-04 | 40.3457 | 30.9513 |
| block3 / 7 | combined-01 | 39.2314 | 30.7147 |
| block0 / 2 | combined-01 | 39.2105 | 30.8355 |
| block2 / 4 | combined-04 | 38.7577 | 30.1628 |

rag.retrieve is the largest retained pre-generation stage in each of these
requests. Combined rag.retrieve median is 25.7375/25.8355 ms in c0/c1;
its descriptive category P95 is 29.2202/31.1872 ms. memory.assemble medians are
2.7967/2.7673 ms and rag.rerank medians about 0.027 ms. The tail is localized
primarily to the retrieve interval; this is not yet attribution to a component
or proof of a causal regression.

Source boundaries matter: retrieval_pipeline.py:108-124 wraps local embedding,
PgVectorStore.hybrid_search, row mapping and c1.documents receipts inside this
span. LocalPorts.embed_one is a fixed local vector stub. PgVectorStore executes
the real hybrid SELECT, including vector parameter formatting and result mapping.
C1 records/hashes retrieved text before the span ends. Existing traces do not
separate database execution, client/scheduler waits and C1 receipt CPU time.
No SQL query plan or per-request CPU split was retained.

source-boundary-proof.json verifies these three app source files directly from
an already stopped worker, with the exact same frozen image in both labels.
Their bytes match the unchanged host sources; local_api.py is also bound by the
original plan. Only inspect/copy reads occurred, without starting any container.

The official clock ends at primary native send, before any primary response
bytes. Downstream SSE body completion cannot explain a pre-send delay. However
SSE setup/primary serialization before dispatch remains inside the original
interval. rag.generate/request spans also include work after that boundary;
their complete durations must not be subtracted from the primary metric.
Trace wall-clock durations are supplemental, not replacements for the retained
monotonic primary clocks. No new S1/S2 inference or logging mechanism is used.

## Coarse resource evidence and limits

All recorded API/PG throttle-count and throttle-time deltas are zero across
32 workers. ES-SSE database deltas report zero block reads and deadlocks.
These coarse/asynchronously published counters do not rule out database CPU,
cache/state effects, lock/scheduler waits or client work.
Whole 45-request worker API CPU totals range 599.513-774.179 ms; they include
warmups and cleanup and cannot assign CPU time to a slow request.

usage_events autoanalyze timestamps changed during c0 block1 and c1 block2
observation windows. No within-window timing or causal contribution is known;
other tail blocks show no such timestamp change. Reported API frequency endpoints
range 0.799554-4.855986 GHz; they were sampled outside measured requests. Host CPU
counters include the experiment, and SMT siblings are mostly idle in these
coarse windows. No thermal, exclusive-host, CPU-migration, disk or maintenance
cause is established. None authorizes exclusion or host tuning.

## Smallest recommended next step, not executed

Before another A/A, prepare/authorize a request-free local PostgreSQL diagnostic.
Use a fresh disposable clone with the same pinned image/schema/P3/roles/settings,
rag_app tenant context and read-only transactions. Evaluate the exact retained
hybrid SELECT/parameters for all five ES combined cases and the five ES document
controls, one bounded diagnostic attempt per case. Retain EXPLAIN ANALYZE/BUFFERS/
SETTINGS output and exact inputs. No app/harness/query optimization, new observer,
campaign request, threshold change or favorable calibration rerun is included.
This can inspect database execution/plans without invoking rewrite/evaluator/
primary generation; it cannot by itself isolate C1 CPU or certify G6 PASS.
Any instrumentation or performance experiment afterward needs a separate scoped
proposal and approval. The current offline evidence justifies a diagnostic
target, not a production fix or a declared root cause.

USD 0, no external/provider calls, no runtime/P5/harness/global-env/model/
threshold/accounting/schema/grant/host-policy changes, G9, Notion or commits.
Keep In Progress / Implement / DECISION_FREEZE_PASS, CONTROLLED_G6_FAIL and
BLOCKED_CONTROLLED_G6_FAIL. R2 LOW remains documented; no source fix is claimed.
