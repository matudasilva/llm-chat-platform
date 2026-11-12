# Proposed G6 measurement amendment: balanced blocks and fixed preparation

**MEASUREMENT_AMENDMENT_PROPOSED_AWAITING_APPROVAL** — design only, 2026-11-08.
Preparing this proposal does not authorize harness implementation, service startup,
database operations, another calibration, a formal G6 run or paid requests.

## Basis and limits

The [latest A/A](../aa-runs/261108131511/report.md) completed 840 functional
requests but failed three of four symmetric 5% comparisons. Image/configuration,
logical data, CPU affinity, resource limits, native payload parity and evidence
integrity were already controlled. The reviewed retention correction remains
valid; its performance benefit was not established. All historical FAILs remain.

Remaining differences include process initialization, temporal separation of
105-request arms, document-only warmup, PostgreSQL physical state and shared-host
activity. None is a proven cause. This amendment tests the combined reproducibility
of a prespecified preparation/schedule; it cannot attribute a gain to one change.
It is not an application optimization or a promise of PASS.

## Preserved contract

- Same machine and existing immutable images: optimized C1 `4e68…` in both A/A
  labels; exact full digests and source evidence in `contract.json`.
- EN/ES × JSON/SSE; 100 measured requests per arm/cell, 25 per category:
  document/history/combined/empty. The original 20 business cases per language
  each occur five times per measured cell. Contents/history are unchanged.
- Original interval: ASGI ingress to entry of the primary serialized native SDK
  memory transport, before primary Capture bookkeeping. No wait subtraction,
  observer disabling, forced GC or fine profiling.
- Full C1 capture/attempt/lifecycle/hash validation in both A/A arms, response
  validation, quiescence and the reviewed guarded cleanup after every request.
- Concurrency 1; one attempt per admitted identity; no automatic resume, resend,
  replacement, retrospective exclusion or favorable repetition. R=1.
- API CPUs 0,2; dedicated PostgreSQL CPUs 4,6; existing 2-CPU/2-GiB limits,
  auxiliary caps/images, P3, roles, schema, locale, model and effective settings.
- P2 credential scrubbing, empty dotenv, network-none PostgreSQL namespace,
  loopback-only Redis/OTLP, memory-native provider and local embedding/rerank stubs.
  Fallback absent, routing static, shadow off. No image download or paid calls.
- All G6 thresholds stay fixed: formal C1/C0 p95 overhead <= +5%, plus the
  separate unchanged live gates. Campaign bound USD 4.15355688, hard cap USD 5;
  P5 and paid admission are untouched.

## Exact proposed changes

| Surface | Existing calibration | Proposed calibration |
|---|---|---|
| Process seed | `PYTHONHASHSEED` unset | `41` in every worker, before interpreter startup |
| Worker lifetime | One 105-request worker per arm/cell | Four fresh 45-request workers per arm/cell |
| Warmup | Five document cases per arm/cell | All 20 cases once before each measured block |
| Measured schedule | 100 consecutive samples per arm/cell | Four paired blocks of 25, balanced first/second order |
| PostgreSQL preparation | Restored equal logical data | Same restore plus explicit equal ANALYZE sequence |
| Host evidence | Affinity/topology/cgroup counters | Those proofs plus coarse CPU-load/frequency samples |

### Blocks and warmup

Cell order remains EN JSON, EN SSE, ES JSON, ES SSE. For each block run its two
arms serially to completion, including cleanup and worker teardown, before the
next block. Each worker starts once, executes 20 warmups then 25 measurements,
and exits. There are no persistent-worker handshakes, request overlap, new local
server or control plane. Existing small-crossover structure is a reference;
its old worker cannot be reused unmodified because it lacks the reviewed cleanup.

| Cell | Block 0 | Block 1 | Block 2 | Block 3 |
|---|---|---|---|---|
| EN JSON | A then B | B then A | B then A | A then B |
| EN SSE | B then A | A then B | A then B | B then A |
| ES JSON | A then B | B then A | B then A | A then B |
| ES SSE | B then A | A then B | A then B | B then A |

Each arm is first twice and second twice in every cell. Both arms receive the
same measured business sequence within a paired block. Categories are indexed
document=0, history=1, combined=2, empty=3. For block b=0..3 and measured slot
j=0..24, category=(b+j)%4. Within each category, select the sorted case ID at
occurrence_index%5, counting measured occurrences across the whole cell. This
gives 25 per category and five appearances per business case in each arm/cell.

Warmup order in every worker is five cycles: for case index 0..4 visit document,
history, combined, empty, using that category's sorted case at the index. Every
warmup has separate conversation/request identities and full functional/evidence
validation. No duration-based warmup extension or steady-state claim. This
changes measured order and warmup prospectively, not the measured case multiset.

The executable manifest must later bind every slot/phase/block/case, fresh UUID5
namespace, fixture projection, order and hash. Pair UUIDs across the two separate
arm databases, never reuse historical IDs. Admission identity is run/arm/request;
each arm has 720 unique requests/conversations, including warmups. A/A has
1,440 globally unique C1 accounting instances. No UUIDs are allocated by this
design document and `contract.json` is not an executable manifest.

### Process and PostgreSQL preparation

Set and verify `PYTHONHASHSEED=41` only in disposable worker environments; retain
an identical non-secret string-hash probe and interpreter identity. It does not
make UUID allocation, allocation/GC behavior or OS scheduling deterministic.
Retain default GC and all other reviewed application/provider settings.

Create a new dedicated cluster and two fresh paired databases from the unchanged
schema/P3/locale/role procedure. Seed all warmup/measured histories identically.
In each database, outside measured requests, run schema-qualified ANALYZE once
on this exact sorted `public` table list: `alembic_version`, `chunks`,
`conversations`, `documents`, `messages`, `rag_request_metrics`, `usage_events`.
Require the restored ordinary-table inventory to match; the retained source
schema corroborates this list. Freeze the SQL, effective statistics/autovacuum
settings and completion receipts before admission. Do not alter planner settings,
indexes, constraints, extensions or grants. No production or historical DB writes.

After ANALYZE, complete the same read-only identity/RLS/business/config proofs
for both arms, then perform the fixed warmups inside each worker. Do not flush
OS/PostgreSQL/Redis caches, install prewarm extensions or add per-case SQL probes.
ANALYZE normalizes the preparation procedure, not physical page residency or
identical planner statistics. Capture cumulative DB activity before/after each
block outside the request interval; retain background-maintenance observations
without excluding samples. Cache and shared-cluster interactions remain limits.

### Host observations, not host tuning

Immediately before and after each worker, retain timestamped `/proc/stat`
counters for CPUs 0..7 (including SMT siblings), existing cgroup counters and
reported `scaling_cur_freq` for CPUs 0,2,4,6. Keep topology/governor/affinity
checks. Files must be readable at preflight; a missing/reset required counter
invalidates the proof. Reads occur outside measured requests, without a new
background sampler or exporter. Retain raw values; never correct request times.

These frequency endpoints are reported samples, not proof of actual frequency
throughout a request. Per-CPU load includes the experiment itself and cannot
identify unrelated processes. No exclusive-core or thermal-stability claim.
No host governor/SMT/priority/affinity-policy change, system-wide reservation,
process termination, cloud acquisition or production infrastructure change.
No new load/frequency threshold or noisy-sample exclusion is introduced.

Database observations are `pg_stat_database` transaction/block/tuple/deadlock
counters and reset identity for each arm DB, plus `pg_stat_user_tables` maintenance
timestamps. They are cumulative/asynchronously updated observations, not precise
per-request waits. Keep recorded maintenance activity; do not tune or subtract it.

## Exact volume, cost and evidence

| Quantity | Per arm/cell | All arms/cells |
|---|---:|---:|
| Fresh workers | 4 | 32 |
| Measured requests | 100 | 800 |
| Warmup requests | 80 | 640 |
| Total local requests | 180 | **1,440** |

This is 600 more local requests than the previous 840, all extra warmups. External
provider/egress/paid spend remains **USD 0**. Local CPU/disk time is real; no
elapsed-time guarantee is claimed. Original request deadline 300 s and cleanup
bound 10 s stay fixed. Any unresolved worker/cleanup prevents new admission;
preserve receipts, settle ownership and never restart the run automatically.

With current fixtures, prepared DBs each contain 720 conversations and 17,280
history messages; final DBs must contain 720 conversations and 18,720 messages.
Prove all original histories plus exactly one user/assistant exchange for each
of the 720 requests per arm, including warmups. Validate canonical new message
UUIDs before normalizing only those generated IDs for paired comparison. Retain
P3 fingerprint/content, RLS/schema/locale/roles/config proofs, 32 raw worker
receipts/logs, per-request timings/dispatch hashes, host/DB receipts, audit,
exclusive execution-start marker, frozen sources and independent reviews.
As before, full C1 chains are validated by the reviewed worker; compact receipts
are retained, not a separately replayable raw chain for every request.

## Acceptance and disposition

Require all 1,440 functional/evidence/transport/persistence checks, exact measured
population, resources, source/config identities and empty P2 audit. Incomplete,
failed, ambiguous or drifted evidence yields no valid calibration PASS and stops
admission. A complete run retains all 800 measured durations. Do not discard
outliers or pool languages/paths. Warmups never enter the primary percentiles.

For each arm/cell, pool its four blocks' 100 raw measured durations. Use original
nearest-rank p95 (sorted index 94); report p50/p99/max and descriptive block/order
results. Do not average block p95s, replace the metric by paired differences,
subtract CPU/wait times, or add a confidence-interval escape from the 5% rule.

Keep the existing symmetric A/A test: a*100<=b*105 AND b*100<=a*105, including the
zero rule. All four cells must pass for AA_CALIBRATION_PASS; otherwise a complete
valid run is AA_CALIBRATION_FAIL. Integrity/incomplete execution is reported
separately and never qualifies. An exit code indicating result publication is
not itself a metric PASS. R=1/N=100 does not establish statistical equivalence.

- A/A FAIL/incomplete: retain it, preserve original G6 FAIL/paid block and stop.
  No automatic new seed, warmup count, schedule, host or repetition.
- A/A PASS: independent postrun review; propose a separately authorized formal
  C0/C1 run using this same approved measurement procedure and the unchanged
  one-sided +5% criterion. No formal execution is included in this proposal.
- A later formal PASS would still not satisfy pending live campaign prerequisites
  or automatically start paid requests. Historical results remain attributable
  to their original protocols; no overwrite, retroactive invalidation or waiver.

## Smallest future implementation and validation surface

After design approval, propose only three new files, leaving existing historical
workers/helpers/tests and app/P5 untouched:

- `experiments/production_graduation/gate_validation/blocked_latency.py`:
  fixed schedule/preparation/controller, source/resource guards and aggregation;
- `experiments/production_graduation/gate_validation/blocked_latency_worker.py`:
  reuse validated capture/native transport/cleanup; one warmup+measured block;
- `tests/experiments/test_orq41_blocked_latency.py`: deterministic protocol guards.

Reuse existing AA preparation/resource helpers and reviewed cleanup with exact
source pins. If implementation needs a wider seam, report it before expanding.
Do not relax original validators that assume 105 rows: add mode-specific strict
180/arm/cell and 45/worker validation in the isolated harness instead. Initial
implementation is A/A only; do not add an executable formal-G6 mode by default.

Required P2 tests: exact counts/case multiplicities/order balance/freshness;
warmup separation; seed propagation before startup; strict ANALYZE allowlist and
read-only proofs; hash/review-before-I/O/exclusive start; JSON/SSE and cleanup
failure stops; C1 integrity and payload parity; host/resource drift/missing data;
nearest-rank pooled aggregation and exact forward/reverse/zero 5% boundaries;
no re-admission/resume and complete final DB projections. Re-run existing AA,
controlled-G6 and cleanup regressions in the pinned image, no credentials/network.
Review source and the exact executable packet independently before execution,
then review raw results and parent-attributed DB proof independently afterward.

## Approval requested

1. Approve the proposed seed/preparation/warmup/block schedule and 1,440-request
   A/A protocol, preserving every threshold and historical result.
2. Authorize implementation and deterministic P2 tests of the three-file harness,
   followed by independent prospective review.
3. Authorize the single local A/A execution separately once that exact reviewed
   manifest is ready. Neither design preparation nor implementation approval
   implicitly authorizes it. Formal C0/C1, paid execution and host changes remain
   outside this amendment's immediate authorization.

This task changes only this proposal/contract/document validation and minimal
planning references. No app/P5/runtime/provider/retry/retrieval/SSE/persistence,
schema/grant/global-env/model/accounting/threshold change; no service or request,
external network/provider call, Notion, commit or deployment. Global Implement /
DECISION_FREEZE_PASS and BLOCKED_CONTROLLED_G6_FAIL remain unchanged.
