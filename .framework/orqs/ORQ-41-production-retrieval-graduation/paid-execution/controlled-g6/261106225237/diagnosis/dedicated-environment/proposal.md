# Dedicated measurement environment: evaluation and approval boundary

**DEDICATED_ENVIRONMENT_EVALUATION_READY_FOR_TARGET_SELECTION**.
Read-only evaluation/design only. No benchmark, host setting, service operation,
runtime/harness change, environment provisioning or provider request authorized
or performed by this evaluation. Prior360-request diagnostic and its review
remain immutable; G6FAIL/paidblock remain, global Implement/DECISION_FREEZE_PASS.

## What is actually bounded

Stage diagnostic261110181827 independently verified360functionalrequests,
all360C1contexts/native chains, transport/evidence and final PostgreSQL atomic
exchanges/history preservation. No new BLOCKER/HIGH/MEDIUM remained within that
scoped review. This does not rule out every runtime defect or establish latency
graduation. The original identical-image A/A failed2/4cells.

Observed instrumented hybrid-retrieval medians6.486–7.817ms in document/combined
groups are a useful localized envelope. Final-cap0.120–0.209ms and payload
construction0.122–0.283ms medians do not identify the cause of the p95 variation.
These are overlapping/instrumented stage statistics, not additive causal shares
of total latency. Client SQL spans still combine server/driver/scheduling effects.
No defensible percentage of the overall investigation being solved can be given.

Current read-only inspection finds intel_pstate/powersave on CPUs0,2,4,6,
configured0.8–5.6GHz ranges, SMTsiblings0–1/2–3/4–5/6–7 and an empty kernel
isolated-CPU list. These are endpoint/config observations, not historical
effective frequency or proof that every form of CPU isolation is absent.
Affinity/resource limits were already applied in the last A/A; repeating them
alone would not establish a newly dedicated environment or explain its failure.

## Proposed target and controls

First choose an available target: preferably the existing machine reserved for
an exclusive measurement window, if host administration can establish and verify
the necessary controls safely. Otherwise use another genuinely dedicated Linux
machine. A shared VM with unknown host contention is not automatically better.
No remote machine, cloud instance, new cost or downloads are assumed/authorized.

Before provisioning or benchmarking, inventory the chosen target read-only:
CPU/SMT/NUMA topology, available controllers and permissions, OS/kernel/Docker,
actual concurrent workloads, memory/swap/disk, power/frequency policy and caches.
Do not collect secrets. Select exact API and PostgreSQL physical cores plus
housekeeping placement for the controller, Redis/collector and other tasks.
Any reservation must consider SMT siblings; Docker --cpuset-cpus alone is not
exclusive host ownership. Record interrupt/kernel-work residuals honestly.

Propose exact reversible changes only after that inventory. No blanket
`pyperf system tune`, killing user workloads, pruning containers/data, stopping
production/source services, realtime priority or disabling telemetry. If CPU
partitioning, workload placement, frequency/boost/power control or a reboot is
needed, specify original values, owner, changes, verification and restoration
before asking for approval. A performance governor does not by itself prove a
constant effective clock or sufficient thermal headroom.

Verification must establish the claimed reservation/placement and unchanged
policy before and after the run, rather than infer it from a quiet snapshot.
Record permitted existing CPU/cgroup/maintenance observations outside the
request interval. Missing proof invalidates the environment claim; no automatic
extra load experiment or new per-request profiler is introduced here.

## Required prospective amendment

The approved harness pins exact CPU topology/governor and checks it before
preparation and in workers. Changing the governor or hardware would correctly
fail these guards. Therefore do not tune the host and bypass the mismatch.
Prepare an explicit environment-only amendment for the selected target, with
strict new identity binding and review; preserve historical contracts/receipts.
No such harness change or environment amendment is implemented by this document.

Keep the775application image, fullC1 in both A/A labels, P3, ordinary planner/
maintenance settings, local provider transports, model/region, static routing,
fallbackNone, shadowOFF, localOTLP, concurrency1, atomicity and original timing
boundary. Keep the reviewed 4blocks x20warmups/25measured per mode/cell:
**1440localrequests=800measured+640warmups**, fresh identities/databases, one
attempt each, unchanged pooled100 nearest-rank p95 and symmetric5% A/A rule.
This is a proposed future calibration volume, not current execution permission.
The coarse-stage observer is not installed in that acceptance measurement.

Freeze and review the target-specific packet before one execution is authorized.
If the unchanged calibration fails, retain FAIL and stop: no favorable repeat,
threshold increase, post-hoc sample removal or speculative runtime optimization.
Consider the measurement question unresolved and require a new operator decision.
If it passes, independently review results before proposing separately approved
formalC0/C1 G6. A/A alone never grants G6PASS or paid admission. The diagnostic
image is not silently substituted for the formal baseline.

## Current deliverable and decisions

Current changes: this proposal, a reproducible read-only host/source audit and
minimal planning/handoff references. External provider costUSD0; documentation
lookups are separate from isolated validation. No app/P5/harness/model/threshold/
accounting/schema/grant/globalenv change, new service, G9,campaign,Notion or commit.

Next decision: whether the operator can reserve this machine for an exclusive
window, or supplies another dedicated target. Then prepare the exact host profile,
rollback and environment-identity amendment for approval. No host mutation or
1440-request execution is implied by target selection or this evaluation.

Primary references:
- https://pyperf.readthedocs.io/en/latest/system.html (pinning, isolation and power variability).
- https://docs.kernel.org/admin-guide/cgroup-v2.html (cpuset partition semantics and administration).
