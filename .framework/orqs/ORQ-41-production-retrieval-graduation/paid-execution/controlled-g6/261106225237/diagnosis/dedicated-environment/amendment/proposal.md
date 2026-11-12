# Prospective environment-only amendment: current host performance profile

**ENVIRONMENT_AMENDMENT_PROPOSED_NOT_IMPLEMENTED**. Operator approved preparation
and independent review only. No host mutation, harness implementation, service
provisioning or A/A request is authorized by that approval.

## Exact change and preserved contract

Bind the current operator-selected host's additional power-policy identity:
intel_pstate active; governor powersave; EPPperformance; min800000/max5600000kHz;
turbo enabled(no_turbo0). Pin per-policy values for CPUs0,2,4,6, including their
core/SMT topology, and record their affected policy domains. A missing file,
unknown value or mismatch fails before request admission. EPP and governor are
distinct; historical EPP was not recorded, so there is no historical EPP-delta
or causal-improvement claim. This is a new prospective configuration identity,
not permission to rewrite prior contracts, hashes or FAILs.

API remains on0,2; PostgreSQL4,6; distinct physical cores. Entire SMT sibling
sets0–1,2–3,4–5,6–7 must be considered when controlling interference. Keep the
same775application image/fullC1 in both labels, PG/Redis/collector images, P3,
ordinary planner/maintenance settings, schema/roles/RLS, model/region, flags,
fallbackNone/static/shadowOFF/localOTLP, seed41,2CPU/2GiB and concurrency1.

The future A/A remains exactly1440localrequests:800measured+640warmups,
4cells x4blocks x2labels x(20warmups+25measurements), fresh identities/databases,
one attempt, original ABBA/BAAB order and timing boundary. Pool100raw measured
values/label/cell, nearest-rank index94; unchanged bidirectional5% rule in all
four cells. No coarse-stage profiler, new timing statistic, wait subtraction,
outlier removal, threshold relaxation or favorable repetition. No formalG6 or
paid execution follows automatically from A/A.

## Host-control readiness, separate from metric acceptance

The operator reports closing applications; this is an operator declaration,
not proof of exclusive CPU ownership. Before any future trial, an administrator
must provide the exact supported CPU-reservation configuration and evidence
for this machine. Proposed placement is benchmark API/PG on their current
cores, sibling logical CPUs1,3,5,7 unused by unrelated user workloads, and
controller/Codex/editor/Redis/collector/other workloads on housekeeping CPUs8–31.
Existing quota and affinity alone do not establish this reservation.

Do not blindly create or change systemd/cgroup partitions. Inventory actual
hierarchy/delegation and affected processes first, identify a supported reversible
mechanism, then obtain approval for those exact changes. A missing root-level
partition file is not proof that the kernel lacks cpuset-partition support.
No host-wide process migration, service stop, reboot or privilege change is
included in this design-preparation approval. If reservation is infeasible,
stop with ENVIRONMENT_READINESS_BLOCKED; do not silently downgrade the claim
to a quiet-window snapshot or choose a different machine.

Future readiness must retain configuration and actual placement of relevant
workloads, a timestamped operator exclusive-window declaration, power supply
state, profile stability before/after each worker, and available thermal/
throttling observations. Do not claim constant frequency: performance preference
and turbo remain dynamic. Interrupts/kernel activity remain disclosed residuals.
No new load generator, continuous per-request sampler or speed threshold is
introduced. No snapshot alone proves exclusive use throughout an interval.

Validate environment identity before each worker; observed policy/placement
drift stops new admission. Let an admitted request settle under the existing
deadline/cleanup contract. Retain every admitted sample and drift observation;
the run cannot become PASS by dropping affected samples. A stopped/incomplete
trial is not resumable and does not authorize another trial.

## Verification and restoration contract

Capture actual approved settings, policy domains, cpusets/partitions and process
placement before any administrator action. Restoration applies ONLY to changes
made by that future procedure. Preserve the operator's newly chosen power mode;
do not invent an old EPP value or switch it back automatically. Read back every
restored value and placement. If a restore fails, report cleanup failure, retain
evidence and leave the exact residual state explicit; no false recovery PASS.
Never stop or delete historical/source/production services or data. Own disposable
services may be stopped only after workers settle; retain containers/DBs/markers.

## Smallest future implementation surface, not implemented here

After the target-specific reservation procedure and this amendment are approved,
propose strict environment-binding support in `blocked_latency.py` and a small
read-only profile checker under the campaign harness, with focused tests. Extend
the existing worker environment proof in `aa_calibration_resources.py` only as
needed to read the pinned EPP/driver/limits/turbo identity. Preserve legacy
packet validation paths and exact historical helper hashes; use a new explicitly
approved binding instead of weakening equality or editing old receipts.
Any affected source hash must be pinned in a fresh independently reviewed packet.
No app/P5/native transport, provider, retries or measurement-loop change.

Future deterministic tests must reject missing/duplicate/unknown profile fields,
one-policy mismatch, wrong source/approval hash, unsupported reservation claims,
wrong SMT placement, drift between workers and restoration mismatch. Test the
unmodified p95 arithmetic/population and rejection before I/O. Unit tests use
file/cgroup doubles and no host writes; actual readiness uses read-only proof.

## Approval boundaries and stop conditions

This deliverable is a reviewed proposal, not an executable host procedure or
ready benchmark packet. Remaining requirements: exact administrator-supported
reservation/restore procedure, approval of that host procedure and the minimal
harness binding, implementation/source review, fresh disposable preparation and
exact packet review, then separate authorization of one1440-request local A/A.
No repeated application optimization or database migration is justified here.

External-provider cost for this preparation and the proposed local A/A isUSD0;
CPU/disk/time remain real. Paid capUSD5/effectivebound4.15355688 unchanged.
If the future A/A fails, retain FAIL and stop. If it passes, independent result
review precedes any separate formalC0/C1 G6 proposal. Preserve global
In Progress / Implement / DECISION_FREEZE_PASS and G6FAIL/paidblock. No Notion,
commit, campaign, G9, image download or production infrastructure change.
