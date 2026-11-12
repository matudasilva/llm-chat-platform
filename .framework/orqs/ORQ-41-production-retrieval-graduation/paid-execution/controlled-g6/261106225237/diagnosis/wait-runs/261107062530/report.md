# Wait/GC diagnostic execution

DIAGNOSTIC_WAITS_COMPLETE. One execution of the independently reviewed final plan56e110e4dd374948106579c46dbc17fe70206cef5709120221d0217194174ec9. No new G6 gate was run.

## Integrity

All40 local requests completed successfully:32measured/eight warmups. Native serialized rewrite/primary payload and call order match for paired inputs. Twenty unique valid closed candidate contexts passed the reviewed worker's validation. All bounded GC/SQL/SDK tapes passed correlation, order and coverage checks. Raw candidate chains are validated by the worker but not separately retained in the timing receipt. Exclusive execution-started.json prevents automatic resend.

The parent-executed post-run read-only verifier passes:20conversations/424messages per arm,384 original history messages exact, one user/assistant exchange per conversation, new generated UUIDs canonical/unique and normalized only for paired equality. P3 content, tenant RLS, schema and effective settings are unchanged. This SQL execution is attributed to parent; the independent reviewer can inspect its source and receipt without claiming a separate DB connection.

## Descriptive observations

Signed medians below are computed per paired identity, C1 minus C0. Each category has eight pairs, including only two per language/protocol cell. Negative values favor C1. These are not differences between arm medians and must not be treated as G6 p95 estimates.

| Metric (ms) | Combined paired median | Empty paired median |
|---|---:|---:|
| Preparation wall | -7.815 | -8.530 |
| Whole-process CPU | -4.283 | -6.671 |
| SQL-await interval union | -5.873 | -4.248 |
| GC interval union | +0.086 | 0.000 |
| SDK queued-to-worker-entry union | -0.054 | -0.007 |
| SDK worker-exit-to-return union | -0.043 | +0.027 |

The paired wall ranges cross zero substantially: combined -29.721 to +26.490ms; empty -30.065 to +29.261ms. Source order is associated with the sign: the eight pairs in C0-first cells have median wall delta -10.624ms and CPU delta -6.242ms; the eight pairs in C1-first cells have median wall delta +17.904ms and CPU delta +10.227ms. Thus the arm run second is favored by these pooled order-stratum medians. Order is still confounded with language/protocol cells, fixed process sequence and host time; this experiment does not isolate its cause. It is not proof that original G6 failure was invalid or that source overhead vanished.

Per-arm medians remain separate in analysis.json. Combined GC union medians are0.188ms(C0)/0.479ms(C1), queue0.383/0.319ms, and SQL-await27.661/23.632ms. Empty GC medians arezero and SQL-await7.890/2.974ms. These components overlap, and no subtraction of medians or addition of overlapping GC/SQL/SDK/CPU quantities is valid. SQL spans include await/rescheduling; SDK spans are specific helper observations, not all scheduling. Process CPU counts every process thread. GC request association does not prove request causation.

## Supported conclusion and next decision

The data do not support a GC-only or SDK-queue-only runtime optimization as the solution. Variation and order/cell associations in this small local experiment exceed the known receipt-loop savings. The next useful proposal is a prospective crossover within the same language/protocol/workload cells, with equal warmup composition, to separate source overhead from warmup/order/environment effects. Its design must preserve full evidence, fresh fixtures, resource/config equality and the existing timing boundary, with a frozen schedule before any execution. Such a change is diagnostic only until independently reviewed and approved; it must not replace failed G6 results, relax the5% ceiling or select favorable repetitions. No crossover or additional request is authorized/executed by this report.

## Validation and scope

47 author controls pass in the pinned C1 image under network-none/P2. Independent prospective re-review:17 safe host controls plus two authentic original counterexamples; the GC duplicate/backward validation finding was fixed and frozen before admission. Initial source/plan/proofs remain preserved under initial-review/. Host3.13.9 thread executor teardown incident is recorded in protocol.md; worker3.13.15 controls and actual diagnostic requests completed.

Commands: controlled_latency_waits module prepares; --execute <this packet> executes once after exact-hash review; independent-audit/verify_prepared_databases.py --run <packet> and execution-review/verify_final_databases.py --run <packet> use only readonly SQL/config containers; analyze.py replays retained files. All host operations use scrubbed environment/unshare-rn/P2 and worker topology shares PostgreSQL's network-none namespace without exposed ports. Guard audit is absent/empty, provider transports are memory-only, external calls/paid spend zero. No global dotenv, app/P5/provider behavior/model/threshold/accounting/concurrency/schema change, campaign, Notion or commit. Official G6 FAIL and paid block remain; global Implement / DECISION_FREEZE_PASS unchanged. Independent execution review is recorded separately.
