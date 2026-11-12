# Independent execution review — coarse-stage diagnostic

**STAGE_DIAGNOSTIC_EXECUTION_REVIEW_PASS**. Complete functional/evidence/persistence diagnostic execution verified; no new BLOCKER/HIGH/MEDIUM finding in this scoped review. This is not A/A calibration PASS, formal G6 PASS or causal acceptance of any optimization. **The historical cause remains unresolved; only an observed instrumented envelope is localized.**

## Independent retained-data verification

Executed independent_raw_replay.py once under bounded unshare-rn/env-i/P2 using retained files only. No request, test, provider, Docker, SQL or network operation by reviewer. It independently reconstructs C1 chain hashes, coarse parent graphs, phase/thread/correlation order, clipped wall unions with a sweep-point algorithm, summaries, raw percentiles and counters rather than relying on the diagnostic worker's validator/summary implementation.

Verified immutable source review630a and exact packet reviewe1bb, plan/fixtures/preparation/source/support/config/image bindings. All eight worker hashes and observations match; 45 typed rows per worker (20 warmups then25measurements),360successful requests=200measured160warmups. Sample/case/phase/block/order/UUID derivation matches frozen manifest;360unique(mode,request) admissions and360globallyunique C1 accounting UUIDs. Global/per-worker durable markers retained with matching identities; no extra worker/sample admitted. Both modes run identical775/fullC1; OFF contains no stage observation, ON contains bounded validated tapes. Native rewrite/primary serialized payload hashes and call order agree across every pair.

All8,640retained C1records independently hash-chained and ordinal/previous checked, including request.start/end, tenant/conversation scope, invocation start/end and both native dispatches. Native send instance/request/purpose/invocation and exact record payload projections agree, application/SDK attempts equal1. All360endpoint pairs target the same captured loop native TID while primary reader is the different SDK thread; process CPU/context-switch counters are typed and monotonic. Counter readings are not cross-thread subtraction.

For180ONrows independently validated2,972coarseevents,3,092wait events/1,186complete groups: exact required stage counts/payload purpose, parent containment, request correlation, unique IDs, bounds and thread/phase closure. Reconstructed every clipped stage union, uncovered preparation complement and full thread-CPU summary exactly, retaining original post-cutoff intervals. Intervals overlap; nested stage totals and independent medians cannot be added. Thread CPU across awaits includes other event-loop work; process CPU includes all threads. No wall-minus-CPU waiting-time inference.

All worker resource identities and API/PG/host/database counter deltas match raw observations; clock/global worker order and reset identities pass. Pooled25-sample nearest-rank p50/index12 and p95/index23, process CPU arrays,16cell/category groups and medians exactly match published result/parent analysis.

| Cell | OFF preparation p95 ms | ON preparation p95 ms |
|---|---:|---:|
| EN JSON |14.949291|14.353514|
| EN SSE |15.769158|14.249440|
| ES JSON |16.085842|18.422108|
| ES SSE |19.006106|15.197789|

These descriptive samples do not meet the original N100A/A/G6 denominator and have no metric PASS threshold. ON is lower in three cells and higher in ESJSON; this does not quantify causal instrumentation overhead. Independently verified observed document/combined median envelopes: rag.hybrid6.486004–7.817094ms, finalcap0.119852–0.2090675ms, payload construction0.122459–0.2834085ms; history/empty hybrid0.677929–0.901960ms. This supports localization to an instrumented hybrid envelope, not PostgreSQL-server/scheduler attribution or the historical tail cause. OFF/ON order, time, host/cache and observation perturbation remain confounded.

## Independent-authored final database proof; parent execution

Reviewer authored verify_final_databases.py by adapting the independent preparation verifier with an independent final projection implementation (not merely invoking controller verify_databases). Parent executed it under P2; reviewer inspected source/hash/receipt without a DB connection. It verifies180conversations/4,584messages each, all4,224history messages/UUIDs/content/tenant/order exact, one expected atomic user/assistant exchange for each180requests,360unique canonical new IDs per mode; only generated IDs normalized after validation. Paired normalized business projections equal. P3/RLS/roles/schema/locale/CHECKtruth/config/seed/CPU proofs and original source business/schema preservation pass. No persistence claim relies only on HTTP success. No statement other than read-only SELECT/COPY/catalog operations and transaction-local role/tenant context; metadata-only settings containers did not run app lifespan.

Parent cleanup record reports eight exited workers (no restarts) and three own services stopped with data/containers/markers retained, zero deletions/newrequests, original sourcePG still running. Reviewer inspected these records/source, not a fresh live Docker state. Every frozen protected source/support hash remains unchanged, as required by packet reconstruction. Sources/app/P5/model/threshold/accounting/schema/global-env/host policy unchanged. External/provider/paid calls and task spendUSD0 are supported by frozen memory transports, P2 namespace isolation and empty/absent audits; an empty audit alone is not a general host-network attestation.

## Pre-admission incident and disposition

Initial Docker inspect failure occurred before SQL gate, run marker, worker creation and any request; separate original logs and independent NOT_SENTreview cafaa8ec remain preserved. Underlying Docker stderr was hidden by the old helper, so its cause remains unestablished. Parent fresh metadata/resources/READONLY revalidation preceded the single subsequently admitted experiment using distinct controller-execution logs. It is not a second sample attempt or favorable repetition. No consumed marker was reset or reused.

Author report/analysis/cleanup/commands inspected and hash-bound; reported percentiles/envelope ranges and interpretation agree with independent replay. Parent source64focused/309regression tests belong to source validation, not new execution tests. Scientific cause remains unresolved; no runtime optimization, additional instrumentation/run, formal G6 or paid campaign follows automatically. Keep every historical AA/G6FAIL and current CONTROLLED_G6_FAIL/paidblock. No Notion, commit or deployment by reviewer. This review closes integrity of the approved sole diagnostic, not graduation.
