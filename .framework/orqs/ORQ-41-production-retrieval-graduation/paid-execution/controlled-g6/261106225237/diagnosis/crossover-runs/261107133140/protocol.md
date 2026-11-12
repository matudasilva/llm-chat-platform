# Prospective within-cell crossover diagnostic

DIAGNOSTIC_CROSSOVER_PREPARED_NOT_EXECUTED. No official G6 rerun or gate claim.

## Population and schedule

64 serial local requests:32 measured and32 separate warmups. Four language/protocol cells each have two blocks; each block has one fresh worker per arm, and each worker performs combined and empty warmups followed by one combined and one empty measurement. Both blocks repeat the same business cases (warm case0, measured case1 in each category), on fresh conversation/request UUIDs. Pairing across arms is exact within each block. Across blocks, semantic inputs/history match while identities are disjoint. This is prospective replication, not resending an already admitted identity. Frozen case IDs, histories and schedule are retained before admission.

Each cell sees both C0-first and C1-first orders: EN JSON and ES SSE use C0,C1,C1,C0; EN SSE and ES JSON use C1,C0,C0,C1. Each four-worker cell group runs before advancing to the next cell. Equal warmup composition precedes every measured block/arm; there are16workers and32samples per arm. Shared PostgreSQL/host state remains a limitation; warmed equivalent workloads do not prove identical physical cache/CPU conditions.

Original C0 and reviewed optimized C1 images, PostgreSQL image/P3, twoCPU/twoGiB limits, effective settings, model, request deadline and ingress-to-primary-native-send boundary remain unchanged. Full C1 evidence, raw serialized native body parity, explicit app/SDK attempt checks and bounded reviewed GC/SQL/helper instrumentation remain active. Response cache is already bypassed by the pinned RAG-enabled config; no cache policy changes. No observers are disabled and no timing is corrected. Controller exact-hash review guard and exclusive execution-started.json prevent unreviewed admission or automatic resume/retry.

## Analysis fixed before execution

First require all64 functional/identity/payload checks,32unique valid candidate contexts, complete correlated bounded interval tapes, and empty P2 audit. Postrun readonly DB verification must confirm32conversations/832messages per arm, exact original768history messages plus one user/assistant exchange per conversation, unchanged P3/RLS/schema/config and paired contents, normalizing only newly generated message UUIDs.

For each cell/category compute signed C1-minus-C0 wall and processCPU differences separately for block0/block1, retaining the first/second-arm labels. Report their arithmetic mean as a balanced descriptive source contrast; report half(d_C0-first minus d_C1-first) as a descriptive order contrast. These contrasts assume additive stable effects only for interpretation; block/time effects, host activity and interactions can violate that model. Retain all raw values and report cross-cell summaries by category without statistical PASS or inferred G6 p95.

Reuse the previous clipping/unions rules for GC, SQL-await and existing _call_client queued/entered/exited/returned intervals. Clip to each request's ingress/primary-send window and form unions; do not add overlaps or subtract all-thread processCPU from wall to invent wait. SQL intervals include execution/rescheduling; process-associated GC is not necessarily request-caused. No per-helper/hash/receipt timers; no other scheduling claim.

The experiment only tests whether the earlier order association persists inside the same cell under equivalent warmup composition. It cannot invalidate or replace historical G6 FAIL, certify production/paid readiness, relax the5% ceiling or justify choosing a favorable repetition. No new runtime optimization is implied by its result.

## Validation and restrictions

51 author controls passed in the exact C1 image/Python3.13.15 under network=none and P2 guard. They include crossover freshness/composition/order, review-before-I/O, primary boundary equality, existing wait-observer failures/thread delegation and G6 regressions. The previously diagnosed Python3.13.9 host executor-teardown issue is avoided by running thread tests in the actual worker image, with assertions unchanged. Existing pytest-asyncio deprecation warning is retained.

Preparation and read-only config/DB verification use credential-scrubbed unshare-rn host orchestration and existing local Docker services; no app lifespan/API/provider operation during preparation. Workers will share PostgreSQL's network-none namespace, with no published ports. Provider/embedding/rerank transports are deterministic local stubs. Zero egress/paid calls/spend. No app/P5/provider/retry/retrieval/SSE/persistence/schema/global-env/model/threshold/accounting change, campaign, Notion or commits. Preserve Implement / DECISION_FREEZE_PASS and official G6FAIL/paid-admission block.

Independent harness/plan review is required before any execution. This file records the prospective design; execution and final review evidence are separate.
