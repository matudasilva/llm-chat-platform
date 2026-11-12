# Coarse-stage diagnostic: complete functional execution, causal limits retained

One authorized experiment completed: **360/360 functional PASS**,200measured,
160warmups,8fresh serial workers,360unique full-C1 contexts and360unique
`(mode,request_id)` admissions. No resend/resume or extra experiment. Both modes
use the same775image/fullC1; OFF/ON denote diagnostic observation only.

Source controls64focused/309regression PASS under P2. Initial source findings
R1/R2 were fixed and independently re-reviewed before preparation. Source review
630a and exact packet review e1bb bind the unchanged4newtechnicalfiles, operator
approvalb220, current505protected files, plan7b53fc0b and fixtures/config proofs.

## Descriptive results; no gate decision

| Cell | OFF preparation p95 ms | ON preparation p95 ms |
|---|---:|---:|
| EN JSON | 14.949291 | 14.353514 |
| EN SSE | 15.769158 | 14.249440 |
| ES JSON | 16.085842 | 18.422108 |
| ES SSE | 19.006106 | 15.197789 |

These are25measurements/mode/cell, not the approved100-per-cell A/A/G6 gate.
ObservationON is faster in3cells and slower inESJSON. This does not establish
that instrumentation accelerates requests or quantify its causal overhead:
time/order/environment effects remain confounded. No sample was excluded, no
p95/threshold changed, and no observation cost or wait was subtracted.

In observed document/combined groups, median `rag.hybrid` wall envelopes range
from6.486 to7.817ms; final-cap medians0.120–0.209ms and native-payload-construction
medians0.122–0.283ms. This localizes a substantial observed interval to hybrid
retrieval, without separating PostgreSQL execution, driver waits and scheduling.
History/empty hybrid medians0.678–0.902ms are retained as controls. Full groups,
raw timestamps, stage/SQL/SDK/GC tapes, process CPU and target/reader thread IDs
are retained. Nested spans/independent medians are not additive; whole-process
CPU is all-thread and asynchronous thread CPU includes other loop work.

The supported conclusion is localization of an instrumented envelope, **not a
proven cause of the historical A/A failure or an application fix**. No runtime
optimization or new benchmark follows automatically. G6 remains FAIL and paid
admission remains BLOCKED_CONTROLLED_G6_FAIL.

## Persistence, attribution and incidents

Controller final proof and the independent-authored READONLY verifier executed
by the parent agree:180conversations/4584messages per mode,4224exact original
history messages plus180expected committed user/assistant exchanges and360unique
new message UUIDs. Only new UUIDs were normalized for paired equality. P3/RLS/
roles/schema/locale/config/seed/CPU proofs and original source business identity
remain preserved. Parent replay also revalidates every closed C1/native chain,
stage tape, endpoint identity, worker hash and published result. The reviewer
does not claim a direct SQL/Docker connection.

The first CLI invocation failed on Docker metadata inspection **before** the
execution marker, SQL gate, worker creation or any request. Original error logs,
independent no-admission review cafaa8ec and fresh resource/READONLY revalidation
are retained. The eventual execution used separate logs and exited0, stderrempty.
This is one experiment, not two request attempts. Initial Docker stderr was
hidden by the existing helper; its original failure cause is unestablished.

No app/P5/old-harness/provider/retry/retrieval/SSE/persistence/model/threshold/
accounting/concurrency/schema/grant/globalenv change. Zero external/provider/
paid requests and external spendUSD0 under P2. Existing images only; no campaign,
G9, host tuning, Notion or commit. Global In Progress / Implement /
DECISION_FREEZE_PASS is preserved. Final independent result-review and own-service
cleanup receipts are recorded separately; this report does not substitute for
either receipt.
