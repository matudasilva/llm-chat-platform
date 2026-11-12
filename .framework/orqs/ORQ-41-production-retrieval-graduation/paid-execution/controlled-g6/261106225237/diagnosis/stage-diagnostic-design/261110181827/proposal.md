# Next local diagnostic: coarse stages with an observation-off control

**STAGE_DIAGNOSTIC_DESIGN_READY_FOR_APPROVAL**. Design and pure preview only.
The operator requested continuation with the next test after the retained-data
diagnosis. This packet makes that test concrete before the necessary harness
implementation and execution approval. No runtime/harness implementation,
database preparation, service operation or request has occurred here.

## Question and reuse

Locate which observed stage contains the pre-dispatch variation, and determine
whether coarse observation itself substantially perturbs the descriptive
measurements. This is not an A/A calibration, a new G6 run, a p95 correction or
a promise to identify the historical cause. Keep every previous FAIL.

Retained lexical A/A261110150634 establishes same-image/full-C1 functional
success with failed reproducibility in ES JSON/SSE. The offline analysis
261110173331 localizes the dominant tail clusters to individual workers but
cannot identify per-request SQL, Python or scheduling contributions.

Earlier `controlled_latency_profile.py` wrapped thousands of receipt/hash
operations and could not calibrate its own fine-grained overhead. Do not
repeat that profiling design. Earlier `wait_observer.py` already supplies
bounded SQL-await and SDK handoff intervals, correlation validation and
restoration. Reuse it unchanged. Derive a separate diagnostic request loop
from the full-C1 blocked worker; reuse its native memory transport, lifecycle/
quiescence, evidence validation, cleanup and low-level database/resource helpers
without changing their source.

One concrete seam limitation matters: `blocked_latency_worker.run_block` owns
its endpoint timestamps and private `current` dictionary; it offers no callback
at those endpoints. Wrapping `capture.sent` outside it would record CPU after
its bookkeeping and mislabel the boundary. Therefore the new diagnostic worker
must carry its own small derived loop, preserving the original wall timestamp
as the first operation and adding adjacent CPU/counter reads. Do not monkeypatch
the global clock or modify the approved blocked worker to get a hook.

## Fixed prospective workload

Both labels run the same pinned lexical image
`sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852`
and complete C1 accounting. They differ only in diagnostic observation:
`off` has aggregate endpoint clocks; `on` also installs coarse stage, SQL-cursor
and existing wait-observer hooks. These labels do not mean C0 versus C1.

Use the complete original block-0 population in all four EN/ES x JSON/SSE cells,
not selected historical slow samples. Each fresh worker gets the same 20
representative warmups and 25 measured slots. All four document/history/
combined/empty categories and all 40 existing business cases are retained.
Document/combined is the primary diagnostic focus; history/empty and EN are
controls. Slot order and histories come from the reviewed fixture snapshot;
all request/conversation/history UUIDs are newly namespaced. Paired modes share
sample/request identities in separate disposable databases; admission identity
is `(mode, request_id)`, not request UUID alone.

Exactly **8 serial fresh workers, 360 local requests: 200 measured and 160
warmups; concurrency1, one attempt per identity, one execution**. Each mode has
180 conversations and 4,224 exact prepared history messages. Expected successful
final state is 180 conversations and 4,584 messages per mode: unchanged histories
plus exactly one committed user/assistant exchange per request. No automatic
repeat, replacement worker, request resend, new sample, outlier removal or
adaptive volume increase. These are 25 descriptive measurements per mode/cell,
not the 100-per-cell sample required by the approved A/A gate.

Freeze this mode order: EN JSON off/on; EN SSE on/off; ES JSON on/off;
ES SSE off/on. It balances first position over cells but does not remove
within-cell time/order confounding. On/off differences are descriptive observer
sensitivity checks, not unbiased estimates of observer overhead.

## Exact observable seams

Install wrappers/listeners only in the new diagnostic worker's memory after
normal imports and before requests; restore in `finally`. Never edit `app/`,
route files, production startup or existing harness modules. Call each original
exactly once with identical arguments; preserve returns, exceptions,
cancellation, decorators and the actual called aliases.

| Label | Existing seam | Interpretation |
|---|---|---|
| history.read | `SqlConversationHistoryAdapter.fetch_ordered` in `app/services/conversation_history_adapter.py` | Ownership/read/materialization envelope; includes awaits |
| rag.total | `RetrievalPipeline.retrieve` | Retrieval envelope, including its existing evidence work |
| rag.rewrite | `RetrievalPipeline._rewrite` | Original decorated rewrite envelope |
| rag.hybrid | `PgVectorStore.hybrid_search` | Hybrid SQL and result-materialization envelope |
| rag.rerank | `RetrievalPipeline._rerank` | Existing local rerank envelope |
| context.final_cap | Actual `chat.enforce_added_context_cap` callsite alias | Synchronous final packing/cap envelope |
| provider.payload | `bedrock_provider._build_payload` | Render/native payload construction, labeled rewrite/primary |
| sql.cursor | SQLAlchemy `before_cursor_execute`, `after_cursor_execute`, `handle_error` on the diagnostic engine | Driver/cursor await interval; not pure server execution |
| sql.await / sdk.handoff / gc | Unchanged `WaitObserver` | Existing observed await, SDK queue/entry/exit/return, process GC intervals |

No per-digest, receipt, Evidence.add, logger or exporter wrapper; no sampler,
new dependency or new observability architecture. Keep the existing request
owner, provider purpose and native dispatch boundary. Link coarse events to
request UUID, conversation/tenant from the frozen manifest, C1 accounting
instance, stage/parent invocation, thread and mode. Async nesting must use
context-local ownership, not the old synchronous profiler's thread-local stack.

At ASGI ingress and the first primary native-send entry, retain monotonic and
whole-process CPU timestamps in both modes. The boundary's wall timestamp must
remain first, before optional readings/bookkeeping. Coarse spans additionally
retain thread CPU and thread identity. Read voluntary/involuntary context-switch
counters for the event-loop thread only at the request endpoints in both modes;
retain counters rather than converting them into scheduler waiting time.

Sync thread CPU is a measured thread interval. Across an `await`, it also counts
other work on that event-loop thread. Whole-process CPU includes all threads.
None is exclusive request CPU or a complete decomposition of latency. Never
subtract process CPU from wall time to claim waiting time. `AsyncSession.execute`
and cursor spans can narrow an envelope, but do not separately measure pool
acquisition, PostgreSQL execution and OS rescheduling.

Cap new coarse events at128/request and existing wait events at256/request;
overflow or observer failure invalidates diagnostic evidence without changing
the request's functional result. Retain bounded tapes through actual completion
and quiescence, then validate. Preserve full raw intervals, including those
crossing the primary cutoff; only their clipped intersections with preparation
may be summarized. Union overlapping wall intervals; do not sum nested spans,
independent medians, CPU and waits. Instrumentation stays enabled through SSE
completion; post-cutoff records remain clearly separated.

## Integrity before interpretation

Before any admission, bind the approved design, final harness/tests/review,
image and source inventory, current effective settings/seed, fixture/plan hashes
and exact packet approval. The preview is deliberately not `plan.json` and is
not executable. No existing frozen A/A contract or controller guard is amended.

After implementation approval, create one new disposable PostgreSQL/Redis/local
collector namespace using already pinned local images only. Restore P3 into
two fresh databases, verify corpus fingerprint/content, schema, roles/RLS,
locale, complete fixture/business parity and the prior seven-table ANALYZE
procedure. Keep ordinary planner/statistics/autovacuum behavior. Preserve all
old containers/databases/data/markers; no reset, cache flush or source writes.
Check free disk before cloning; stop on insufficient capacity, never prune old
evidence to make room.

Keep API CPUs0,2 and PostgreSQL4,6, two-CPU/two-GiB limits, seed41 and unchanged
governor. Record configured/effective affinity, topology, worker CPU deltas,
host-frequency endpoint snapshots and database counters outside request timing.
Affinity does not establish exclusive cores or constant operating frequency.
No host tuning, realtime priority, load generation or extra query per request.

Use P2/network-none with absent external credentials and disabled metadata/
dotenv discovery. Native generation, embedding and reranking stay local/stub.
FallbackNone, static routing, shadowOFF and local-only OTLP remain. The model,
region, flags and thresholds stay configured as in the accepted image/environment.
No external provider, G9 or paid request, image download/build or infrastructure
change. Existing P5 and its S1/S2 corroboration remain untouched; provider-call
counts must never become an S1/S2 inference mechanism.

Validate every response/JSON/SSE terminal, correlation and complete full-C1
evidence after quiescence. Unexpected retry/evaluator behavior, failed request,
missing/duplicate/out-of-order evidence, observer error/overflow, cleanup failure,
resource drift or payload mismatch stops new admission and leaves the diagnostic
invalid/incomplete. Let the admitted local request settle; do not cancel it just
to obtain a nicer sample. Persist all failures; never resend. Enforce the existing
300-second request deadline and 10-second cleanup bound. An exclusive run marker
and per-worker markers prevent accidental restart/resume. Capture both worker
output streams in new diagnostic artifacts, without changing historical logs.

Final independent READONLY verification must prove exact original histories,
unique newly generated message IDs, one exchange per successful request, P3/
schema/roles/RLS/source preservation and normalized paired business equality.
Do not infer persistence from HTTP success. For incomplete execution reconcile
only admitted requests; never claim complete 360-request evidence.

## Prespecified analysis and stopping rule

Report all raw endpoint/stage intervals and paired per-cell/category/case values,
warmups separately, on/off differences and the unchanged absolute timestamps.
Focus on whether a long observed preparation interval is also long in
`rag.hybrid`/SQL-await, synchronous cap/payload CPU, SDK handoff or the uncovered
preparation envelope. Label overlap and all unobserved work explicitly. Do not
force percentages to sum to100 or identify a server/OS cause from client timing.

An observed coincidence localizes a diagnostic envelope; it is not proof of
the cause of the old tail cluster. On/off timing shifts may reflect observation
and temporal noise. Without reproducible supporting evidence, do not propose
an application optimization. If no useful localization occurs, or the observer
visibly perturbs the path, stop with **CAUSE_UNRESOLVED** and state the missing
evidence. No second run or more instrumentation follows automatically.

Successful diagnostic completion requires complete functional, evidence,
transport, persistence and isolation proofs; it does not require faster p95.
Retain G6FAIL/paidblock regardless of diagnostic outcome. Future dedicated-host
or scheduling investigations would require their own scoped proposal.

## Smallest future implementation and controls

Add only:

1. `experiments/production_graduation/gate_validation/stage_latency.py`: bounded
   preparation/controller, strict new diagnostic schema/identity/start guards;
   use existing helpers without changing old contracts or controllers.
2. `experiments/production_graduation/gate_validation/stage_latency_worker.py`:
   derive the small request loop from `blocked_latency_worker.run_block` with
   the fixed block-0 population, full-C1 installation and native memory transport;
   preserve its first-operation wall timestamps and functional/cleanup checks,
   adding adjacent endpoint CPU/context-switch readings and sidecar tapes.
   Verify the derived call sequence/boundary against the frozen source in tests;
   the existing worker itself remains unchanged.
3. `experiments/production_graduation/gate_validation/stage_latency_observer.py`:
   reversible coarse sync/async wrappers and engine listeners, context ownership,
   bounded sidecar records; reuse the unchanged wait observer.
4. `tests/experiments/test_orq41_stage_latency.py`: deterministic controls.

Test fresh paired population and collisions, exact360/200/160 volume and order,
unknown-field/image/source/config/review rejection before I/O, missing approval,
single-start/no-resend, on/off full-C1 parity, result/error/cancellation identity,
async nesting and thread ownership, restoration on exceptions, bounded overflow/
clock failure without functional mutation, stage/SQL error closure, cursor tags
without SQL/parameters, native cutoff before bookkeeping, intervals crossing
cutoff, overlap-safe unions, JSON/SSE completion/quiescence, cleanup failure and
observer-off installing no stage hooks. Fake clocks/barriers, no sleeps or
performance assertions in unit tests.

Run focused controls first in the existing pinned image under P2, then blocked
A/A, wait/profile, controlled-latency and cleanup regressions only as affected.
No host native-SDK execution. Review the new source and exact prepared packet
before the sole request execution, followed by retained-result and final DB
review. No independent review has been performed by this design step.

## Approval boundary and cost

Current work changes planning/design evidence only. Proposed implementation
touches the four new files above and minimal planning/evidence. External provider
cost is **USD0**; local CPU/disk/container time is real and duration is not
guaranteed. Existing images/dependencies are reused; fail rather than download.
The historical paid ledger, USD4.15355688 bound and USD5 cap remain untouched.

Approve the new diagnostic harness/tests, disposable preparation and review,
then the one fixed360-request local experiment once its exact source/packet
reviews pass. This permits no runtime/P5/threshold/model/provider/retry change,
formal G6, paid campaign, host tuning, G9, Notion write or commit. A failed review
or mismatch stops before admission; do not bypass it.

Repository `AGENTS.md` requires "Propose", "Wait for confirmation", then
"Implement". The previous approved scope was a design for this diagnostic;
the four-file implementation and concrete execution budget are newly specified
here. Global **In Progress / Implement / DECISION_FREEZE_PASS** and official
**CONTROLLED_G6_FAIL / BLOCKED_CONTROLLED_G6_FAIL** remain unchanged.
