# Dedicated A/A workload lifecycle — proposal for approval

Status: DESIGN_PROPOSED_NOT_IMPLEMENTED. Only design/evidence work in this step.
This extends the local campaign harness, not application architecture. Existing
shared-slice impact approval remains valid; no repeat approval of that impact is
requested. No host action, provisioning, benchmark or paid call is authorized here.

## Actual seams and dependencies

Binding source review PASS: ../harness-binding/source-review.json; execution is
still hard-gated. Administrative normal apply/recovery PASS: helper8064 with empty
benchmark slice; original failed drill and sealed helpers remain immutable.

blocked_latency_worker.run_block uses request_deadline(plan[request_deadline_s])
with300s. The nested httpx timeout30 is not a substitute for that ASGI deadline.
The10s lifecycle quiescence bound is INSIDE the300s request deadline. The worker
then releases validated case evidence outside the measured interval and later
closes application/provider resources. Those finalizers have no independent
external completion guarantee. Python cooperative timeouts do not guarantee exit
of a hung event loop or uninterruptible process.

controlled_latency_controller.docker applies240s to every subprocess, including
Docker wait. Expiry can abandon a still-running block/container. Keep that legacy
helper untouched; the dedicated path must use bounded inspect polling, not a
long-lived Docker wait treated as proof of request/worker cancellation.

helper8064 arms a300s timer and refuses recovery while the benchmark slice is
populated. A persistent owned PostgreSQL keeps it populated even after the API
worker exits. The empty-drill timer must NOT supervise the new workload trial.

## Frozen semantics

Keep same candidate in both A/A arms, image/source/corpus/config identities,
1440requests =800measured+640warmups,32 serial workers of45requests,20warmups then
25measurements, ABBA/BAAB ordering, pooled100/label/cell,p95 index94,bidirectional5%,
concurrency1, single attempt and immutable started/settlement receipts. Keep300s
request deadline and10s request cleanup. No new request samples, loopback probes
against /chat, timing subtraction, retry, resume, favorable repeats or outlier cuts.
Existing G9 thresholds and paid accounting are NOT amended by this administrative
lifecycle. Global Implement/DECISION_FREEZE_PASS; G6 FAIL/paid block unchanged.

## Prospective operational bounds (new approval requested)

| Bound | Proposed value | Exact interval / consequence |
|---|---:|---|
| Reservation/admission window |7200s|Monotonic t0 immediately before first CPU mutation until no new permits may be granted. Includes disposable preparation. No renewal or extension. Expiry invalidates incomplete trial, not a performance FAIL or retry permission.|
| Supervisor observation interval |1s maximum nominal interval|Check controller PID+starttime+boot identity, worker state and stop conditions. OS starvation is not claimed bounded; late checks invalidate admission.|
| Supervisor command timeout |5s per read/signal operation|A timeout/unknown result closes admission and requires reconciliation. Never infer process termination from command timeout.|
| Single-use admission permit |1s|Issued after identity/placement validation; worker must consume before expiry outside measurement. Late/ambiguous use is FAILED, not resend.|
| Request processing/cleanup |300s /10s unchanged|Keep existing request_deadline and nested quiescence. No new cancellation or runtime timeout policy.|
| Recovery drain observation |390s|From durable STOP until worker and owned PostgreSQL are proven stopped, or NOT_DRAINED. Covers at most1s permit delay+300s remaining request+30s worker finalization+30s graceful PG handling plus29s observation margin; no guarantee if a process hangs.|
| Graceful service stop observation |30s per service|From an acknowledged graceful stop request to confirmed exit; constrained by the shared390s drain deadline. No forced-kill escalation.|
| Baseline restoration observation |60s|From proven benchmark populated0 to final file/manager/kernel baseline verification. This is a prospective success criterion, not permission to abandon an in-progress recovery command or falsely declare RESTORED.|

7200s is a proposed resource-occupation cap, not a forecast or a new latency gate.
A pathological but deadline-compliant population may not complete within it; retain
all admitted evidence and declare INCOMPLETE/FAILED, never alter the population.
390s is an observation budget, not a promise of cancellation. If request/worker/PG
cannot drain safely, report FAILED/NOT_DRAINED with exact live residuals and retain
the reservation. An operator must reconcile them; do not silently extend or kill.

## Single local supervisor, durable ownership and admission

Use one run-scoped root-owned systemd supervisor unit and one independent one-shot
recovery timer. Both bind a fresh root-owned manifest/helper/hash/journal, exact
controller PID/starttime/boot identity, and exact new disposable container IDs,
images, labels, mount/network/cgroup identities. Container names alone never
establish ownership. Do not grant the workload broad root or Docker capabilities.
The supervisor executes only fixed readback and lifecycle actions for that manifest.
No general command dispatcher, network listener or persistent platform service.

The supervisor outlives controller/terminal death. Unexpected restart enters
recovery-only, never admission or application replay. The independent one-shot
timer fires at t0+7200s even if the controller/supervisor fails; it runs the same
idempotent stop/drain/recovery path. No heartbeat renewal, broad sudoers grant or
unbounded lease extension. Clock evidence includes boot identity; reboot/clock
identity loss invalidates the trial and requires reconciliation, not resume.

Use a narrowly scoped local admission handshake. A fixed-format local Unix socket
owned by the supervisor authenticates the fixed controller and worker peer IDs;
no arbitrary payload/command. Host socket is mounted only into the owned worker.
The worker sends its immutable run/block/sample identity and waits BEFORE the
existing /chat measurement boundary. The supervisor serializes STOP with permit
issuance and fsyncs admission before replying with a one-use, expiring permit.
The worker verifies identity/expiry and records consumption before entering /chat.
No second permit while a request is unresolved. A lost acknowledgment/unknown
consumption leaves an admitted unresolved request: fail closed and never resend.

Before the first permit for a worker: retain its actual Docker/host cgroup/PID/
thread placement evidence, full bound profile, parent hierarchy and image/config
identity. Subsequent handshake checks supervisor/controller/worker identity, stop
state and the current permit. Full profile/placement observations remain before/
after each worker, not a new per-request sampler. All handshake/writes occur
outside the existing ingress-to-primary timing interval. This is harness-only
coordination overhead and must be disclosed; it is not subtracted from any metric.
Boundary checks do not prove interval-wide absence of hostile administration or
kernel/IRQ interference. Existing residual limitations remain explicit.

A STOP linearizes at the supervisor's durable stop transition. A permit committed
before it is already admitted and may settle; no permit can be issued after it.
No admission relies only on a periodically polled unprotected STOP file. Loss of
the socket/supervisor blocks the next request; worker retains evidence and exits
without starting another sample. A permit already issued remains a bounded,
reconcilable in-flight request, not permission for the remaining44requests.

## Normal, failure and interruption sequence

1. Validate/freeze packet, ownership and recovery artifacts before CPU mutation.
   Arm and read back the new supervisor/timer before applying owned CPU changes.
   A new helper version uses the reviewed path/journal/restoration primitives but
   replaces the administrative-only timer contract explicitly; never combine the
   old300s timer with the new7200s lifecycle. Preserve helper8064 and its receipts.
2. Create only approved new disposable services; no changes to the four existing
   local containers/source DB. Prove API/probe/PG ancestry and housekeeping
   placement, P2, source/config hashes and fresh fixtures before any request.
3. Execute permits/requests serially. Receipt FAIL, drift, unknown I/O result,
   controller loss, worker failure or window expiry durably closes admission.
   Preserve every started/admitted sample, including incomplete final blocks.
4. Let the already admitted request use its original deadline and cleanup flow.
   Worker receives no new permits and exits its existing lifespan/provider scopes.
   Retain final receipts, logs, exit status and task evidence. Parent command
   timeout or a missing response does not imply rollback of a committed exchange.
5. Prove API worker stopped and no unowned descendants/DB clients remain. Ask ONLY
   the bound disposable PG for smart/graceful shutdown (pg_ctl smart, pinned PGDATA
   and image user, no fast/immediate mode). Capture actual exit and clean shutdown
   evidence. Unknown outcome is reconciled by inspection, never signal escalation.
   Stop owned Redis/collector gracefully after API exit and retain their logs.
   Pin their exact stop command/signal in the execution packet; no docker stop
   timeout that can escalate to SIGKILL, no rm, prune, container/database deletion.
6. Once benchmark populated0 is proven, restore the owned CPU changes through the
   reviewed journal/identity barriers, final daemon-reload and baseline readback.
   Auxiliary shutdown failure on housekeeping does not prevent this safe CPU
   restoration; overall outcome remains FAILED and auxiliary residuals retained.
   Never stop an occupied benchmark slice or kill its descendants to pass cleanup.
7. Only verified file/manager/kernel baseline parity, original container/power
   preservation and required owned-service exits permit lifecycle PASS and timer
   disarm. A metric PASS cannot override lifecycle failure. Reservation restoration
   and trial result are separate receipts. Cleanup failure never rewrites a prior
   durable sample/terminal receipt or permits a second execution.

On recovery interruption, replay intents and exact before/after identities;
continue only safe idempotent operations. Preserve unrecognized objects and report
conflicts. On supervisor failure, recovery claims the maintenance/admission lock;
no admission resumes. At390s NOT_DRAINED, stop automatic mutation attempts and
report durable residual state for operator intervention. Do not schedule silent
endless retries of an ambiguous request, service stop or administrative action.

## Minimal expected implementation surface, after approval

- New dedicated_lifecycle.py under experiments/production_graduation/gate_validation:
  fixed protocol/client and local supervisor coordination; split privileged host
  operations into a small new sealed helper in this evidence lane if needed.
- blocked_latency.py and dedicated_environment.py: bind the new lifecycle identity,
  prospective limits, ownership/preflight, bounded state inspection and cleanup.
- blocked_latency_worker.py: optional dedicated-only pre-request permit and
  completion notification OUTSIDE existing measurement; legacy loop/timing/result
  and request_deadline behavior unchanged. This additional seam requires approval.
- tests/experiments/test_orq41_dedicated_lifecycle.py plus necessary focused bound
  controller/worker doubles; administrative lifecycle helper tests in this lane.
- Fresh authorization/source-review/execution manifests. No weakening of old hash
  checks; any revised helper/worker requires a fresh exact reviewed packet.

No app/, P5, providers/retries, SQL/schema/grants, power-mode change, model,
threshold/accounting/concurrency, .env, image acquisition or production changes.

## Acceptance matrix and implementation/execution boundary

| Case | Required evidence and outcome |
|---|---|
|Normal no-benchmark lifecycle|Exact ownership/ancestry, serial synthetic permits, graceful own-service exit, populated0, exact baseline restored. No /chat or measurement population.|
|Stop during synthetic in-flight operation|Only committed permit can finish; no next admission; durable result retained; recovery after proven drain.|
|Controller/session loss|Supervisor survives, durable STOP, API closes or NOT_DRAINED; never resend.|
|Supervisor death/restart|Recovery-only; consumed/unknown permits reconciled; timer retained; no new admission.|
|Expiry with PG idle|Stop admission, graceful owned PG exit, empty-slice restore.|
|Slow/hung worker or PG shutdown|No forced kill;390s NOT_DRAINED/FAILED with exact residuals; no false RESTORED.|
|Auxiliary stop fails but benchmark empty|Restore CPU safely; overall FAILED; preserve auxiliary identity/logs.|
|Permit loss/duplication/expiry or receipt corruption|FAILED, unknown admitted request retained, no reuse/retry.|
|Wrong peer, replaced socket, wrong boot/PID/starttime|Fail before permit or mutation; authenticated peer is not inferred from a name.|
|Foreign child, source/config/profile drift|STOP, preserve owned/unowned state, no foreign signal or deletion.|
|Crash at admission/stop/journal/restore boundaries|fsync/hash/identity proof, idempotent recovery; no reset of trial state.|
|Worker lasts beyond240s but request valid|Dedicated inspect loop retains supervision; legacy Docker helper untouched.|
|Late return/cancellation/committed exchange response lost|Retain actual evidence; no inferred rollback or repeated write.|

First implementation validation: deterministic doubles under P2, no host/systemd/
Docker/DB mutation. Independent source review follows. Actual no-benchmark lifecycle
proof with disposable services requires a separate reviewed command/authorization.
The1440-request A/A still requires fresh readiness, exact packet review and separate
one-run authorization. Its metric PASS does not automatically authorize formal G6.

## Decisions requested now

Approve this design and implementation-only scope, specifically:
1.7200s nonrenewable operational reservation window and the bounds above; unchanged
  300s/10s request semantics and no forced-kill fallback.
2.Local supervisor/one-shot timer and dedicated-only per-request permit seam outside
  measurement, including a new sealed helper version (old helper preserved).
3.Graceful stopping of ONLY exact newly owned disposable containers after drain;
  NOT_DRAINED requires operator intervention instead of destructive escalation.
4.Focused P2 implementation/tests and independent review only. No live lifecycle
  drill, service provisioning,1440-request execution or paid campaign yet.

Estimated external/provider cost USD0. Actual runtime of later live checks is not
claimed;7200s is a cap, not an expected duration. No implementation in this proposal.
