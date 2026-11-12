# Single balanced A/A execution: calibration FAIL

2026-11-09. Packet261109162430 completed its one authorized local-stub execution:
**AA_CALIBRATION_FAIL**. All 1,440 requests completed functionally with PASS;
the prospective symmetric 5% P95 calibration criterion fails in ES-SSE.
This is a complete measured calibration FAIL, unlike the previous attempt's
before-lifespan startup interruption. No second attempt or replacement ran.

## Admission and unchanged measurement

The operator's "autorizado" approved the immediately preceding proposal for this
exact packet. execution-authorization.json binds plan
`b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b`,
fixtures `2a2e7668bb9302939391ff996ed13c9b6322326716e6937ab02cf10db92831cb`
and the already independent-reviewed packet/source fix. Actual source/config/
image/topology/resource/seed/P3/read-only database prechecks passed before
admission. The previous failed packet261109141719 and its markers were not used.
The new execution started at 2026-11-09T19:50:13.729133+00:00.

Both labels run the same frozen optimized full-C1 image4e68..., with 32 fresh
serial workers, 20 representative warmups then 25 measurements per worker.
Total: 800 measured + 640 warmups = 1,440 requests, R=1/C=1/one attempt.
Each arm/cell has 100 measured rows and 25 per category; all four blocks are
pooled before P95 calculation. No averaging block P95, outlier exclusion,
overhead subtraction, extra warmup, resampling or threshold change.
The unchanged interval is ASGI ingress to primary native-send entry, before
capture bookkeeping. This remains A/A calibration, not a real C0/C1 G6 result.

## Observed P95

| Cell | Label c0 P95 (ms) | Label c1 P95 (ms) | Symmetric difference | Result |
|---|---:|---:|---:|---|
| EN-JSON | 33.698990 | 34.479325 | 2.315604% | PASS |
| EN-SSE | 33.707476 | 32.971277 | 2.232850% | PASS |
| ES-JSON | 35.503415 | 35.479770 | 0.066644% | PASS |
| ES-SSE | 35.747604 | 38.757704 | 8.420424% | FAIL |

P95 is sorted 100-row element94 (zero-based). Each cell requires both
100*A <= 105*B and 100*B <= 105*A. All four must pass.
The raw integer clocks independently replay in parent-replay.json. No causal
explanation for ES-SSE's difference is asserted by this execution.

The controller exited0 after recording the complete FAIL result; process success
indicates evidence collection completion, not calibration PASS. All 32 workers
exited0 and published their required 45 rows. All 1,440 full-C1 accounting
instance UUIDs are distinct. Native rewrite/primary dispatch payload parity and
resource/config/seed checks passed under the reviewed controller.

## Persistence, integrity and retained evidence

Actual PostgreSQL read-only verification after execution confirms each arm:
720 conversations, 18,720 messages, 1,440 new message IDs, 720 usage_events and
0 rag_request_metrics. Every conversation has its exact frozen history followed
by the one expected user/assistant exchange. The paired normalized business
projection is identical, including expected tenant/role/content/order; RLS,
P3 corpus/locale/schema and role capability checks remain valid. Proof:
post-execution-proof.json and the controller database-final-verification.json.
These SQL checks were executed by the parent; distinct review must attribute
them and must not imply a reviewer SQL connection.

All 500 protected app/experiment/test/global-env files remain byte-identical to
execution-scope-before.json. Source pins were checked before every worker.
Global and all 32 per-worker start markers remain, with raw worker receipts,
per-block observations, timings and payload hashes. No identity may be resumed
or readmitted. No application or harness source changed during this execution.
The prior namespace fix is exercised successfully across all 32 real startups.

Both stdout and stderr of all workers were manually retained separately here,
in addition to the controller's original per-worker stdout logs. This addresses
retention for this run while leaving R2 LOW automatic stdout-only logging
explicitly unfixed. Controller stdout/stderr are retained separately as well.

After the final proof, only this run's dedicated collector/Redis/PostgreSQL were
stopped. Their containers/data and all 32 exited worker containers are retained;
source PostgreSQL remains running and unchanged. cleanup.json records identities.
No reset, deletion, resend or automatic replacement occurred.

## Scope, cost and next decision

P2 used credential-scrubbed orchestration and isolated network-none/container
namespaces, loopback DB/Redis/OTLP only, empty global dotenv, frozen images with
pull=never, and native provider transports terminating in local memory stubs.
Host and worker P2 network audits are absent/empty; no external egress/provider
calls, paid requests, downloads or spend (USD 0). Configuring the pinned
Bedrock model/region is not invoking it. There was no app/, P5, provider/retry/
retrieval/SSE/persistence behavior, model, threshold, accounting, schema/grants,
global-env or host-policy change. No G9, Notion, commit, push or deployment.
Existing 170 source-fix regression results were not rerun or counted as new tests.

The distinct post-execution review and its hash bindings are recorded separately
in independent-review.md/receipt.json. It must replay all raw rows and distinguish
the calibration FAIL from evidence-integrity findings and parent SQL attribution.
No follow-on diagnostic, new A/A, formal G6 or paid execution is authorized here.

Keep global In Progress / Implement / DECISION_FREEZE_PASS, official
CONTROLLED_G6_FAIL and paid BLOCKED_CONTROLLED_G6_FAIL. Any next diagnostic or
measurement proposal must preserve this observed FAIL and receive scoped
approval; this calibration cannot lift paid admission.
