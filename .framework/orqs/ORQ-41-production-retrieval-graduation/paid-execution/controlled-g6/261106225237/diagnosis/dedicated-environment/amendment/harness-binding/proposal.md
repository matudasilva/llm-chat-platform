# Dedicated placement binding: bounded implementation proposal

Status: PREPARED_FOR_OPERATOR_APPROVAL. No executable harness or host change.
The operator-authorized administrative impact and normal apply/recovery proof
remain valid; this proposal does not request approval of that impact again.

## Verified dependencies and concrete gap

- helper8064 normal-path live proof: recovery/transient-path-remediation/
  operator-execution-261111015223/completion.json; independent review PASS.
- blocked_latency.py:715-729 creates API workers with affinity0,2 but without
  CgroupParent and does not check that parent.
- aa_calibration.py:80 creates new disposable PostgreSQL with affinity4,6 but
  without CgroupParent; inspect_environment does not check actual ancestry.
- With system.slice restricted to8-31, those default Docker children cannot
  obtain effective CPUs0,2 or4,6. This is an integration precondition, not evidence
  of a new performance regression. No experiment has been run in this condition.
- aa_calibration_resources.py captures governor/topology but not the complete
  approved EPP/driver/min/max/turbo policy identity.
- helper8064 has a fixed300s watchdog and recover_locked calls ensure_empty before
  restoration. A running disposable PostgreSQL keeps the slice populated even
  after an API worker exits. The administrative drill proved an EMPTY slice;
  it does not prove workload drain, controller-loss recovery or trial readiness.
- A complete1440-request trial is not proven to fit the300s administrative lease.
  Do not merely disable the watchdog, extend its lease silently, or run workloads
  under the administrative-only script.

## Smallest first implementation increment

1. Add an explicit environment binding to the existing blocked A/A packet,
   tied to the reviewed proposal, approved power profile and helper8064 review.
   Keep historical packets and no-binding behavior byte/contract compatible.
2. Only for that binding, create new API/probe containers and the NEW disposable
   PostgreSQL with --cgroup-parent=orq41bench.slice. Keep API0,2 / PG4,6, quotas,
   memory, images, networking, P3 and application settings unchanged. Redis,
   collector and controller remain outside the benchmark slice on housekeeping.
3. Require Docker CgroupParent AND actual host cgroup ancestry/effective masks;
   verify worker affinity and all available thread masks, power identity and
   existing shared-unit placement before admission and after each worker.
   Missing evidence, unexpected populated root groups, foreign descendants,
   identity mismatch or drift fails closed; retain samples, never retry.
   Boundary observations do not prove interval-wide hardware exclusivity;
   retain the approved residual kernel/IRQ and concurrent-admin limitations.
4. Pin the checker and its imports in the executable packet. Keep readings outside
   the measured interval. No continuous per-request sampling or new statistic.
5. Unit-test the binding with command/file/cgroup doubles under P2. No container
   creation, administrative action, API request or image acquisition in this step.
6. Independent source review. Even a successful increment remains NOT EXECUTABLE
   until the workload drain/recovery contract below and exact packet are reviewed.

## Expected technical files

- experiments/production_graduation/gate_validation/blocked_latency.py:
  explicit binding, probe/worker creation, packet hashes and boundary checks.
- experiments/production_graduation/gate_validation/aa_calibration.py:
  optional bound PostgreSQL creation/inspection, preserve legacy callers.
- experiments/production_graduation/gate_validation/dedicated_environment.py (new):
  small read-only strict profile/placement checker and binding validation.
- tests/experiments/test_orq41_dedicated_environment.py (new): focused doubles.
- tests/experiments/test_orq41_blocked_latency.py and test_orq41_aa_calibration.py:
  only assertions needed to prove legacy compatibility and command construction.
- Minimal evidence/approval records in this directory and planning handoff.

No app/, P5, worker measurement loop, provider contract/retry, SQL, model,
threshold, metric population, CPU quota, concurrency or global .env changes.
Do not edit the sealed helper or overwrite historical reviews/manifests.

## Workload recovery contract required before execution

This is a separate necessary extension, not covered by the empty-slice proof.
Specify and review it before starting any new disposable service under reservation:

- Bind ownership to exact newly created container IDs, labels, image/network and
  cgroup identities. Never act on the four existing local containers or source DB.
- On controller loss, expiry or drift, prevent further admission, retain the
  existing admitted request's outcome and cleanup evidence, and never replay it.
- An independent path must prove the API worker is finished and DB clients have
  drained before gracefully shutting down the owned disposable PostgreSQL.
  Preserve containers, databases, logs and allocation markers; no removal.
- Do not use a Docker stop timeout that silently escalates to SIGKILL as proof of
  safe drain. If completion/ownership is unknown or graceful stop fails, retain
  NOT_DRAINED and report exact residual state; never stop an occupied slice.
- Only after actual populated0 may helper8064 perform its reviewed restoration.
- Bind a prospective trial deadline and recovery trigger to the exact packet.
  The300s empty-drill lease is not a benchmark-duration contract. Its replacement
  requires explicit approval, not inference from nominal sample runtimes.
- Prove normal completion, controller death during a request, expiry while PG is
  idle, failed graceful shutdown, unknown descendants and recovery interruption
  first with doubles, then a separately authorized no-benchmark lifecycle drill.

No recovery orchestration implementation is authorized by approval of the first
binding-only increment. Present the exact supervisor/lease/drain design separately;
no new measurement may precede its acceptance and independent review.

## Acceptance and cost of first increment

Reject before admission: absent/duplicate/malformed policy fields; wrong profile,
source or approval hash; wrong Docker parent; matching affinity with wrong ancestry;
SMT overlap; absent/drifting cpuset; foreign child; mismatch on any pinned policy;
incomplete/changed readback. Demonstrate unchanged legacy plans and p95/population
rules (1440total,800measured,640warmups,index94,bidirectional5%,concurrency1).

Validation: focused deterministic tests first, then existing blocked A/A/resource
regressions under unshare network namespace and empty credential environment.
Provider cost USD0. Local test time is not estimated until the selected scope is
collected; no paid requests or campaign budget are consumed.

## Approval boundary

The retained proposal.md explicitly requires approval of minimal harness binding;
contract.proposed.json has harness_implementation_authorized=false, and the host
impact approval does not authorize a benchmark. Requested now: implement/review
ONLY the binding increment above using local tests. Not requested: live host
application, provisioning,1440requests, paid campaign or watchdog-policy change.

G6 remains FAIL; paid admission BLOCKED_CONTROLLED_G6_FAIL. Global Implement /
DECISION_FREEZE_PASS and P5 CLOSED unchanged. No Notion or commits.
