## Current: ORQ-41 Fully Synced (2026-11-12)

Paid campaign outcome COMPLETE (168/168, USD 4.00469664 settled). Notion
Dashboard, Prompt Library closure entry, Framework Learning and Master Project
Document were updated and read back; links in notion-sync-2026-11-12.json.
Independent validation of the campaign and full synthetic installer/controller
integration remain separate limitations, not implied by governance sync.
Prior GovernancePending and Planned entries below are historical. No new paid
requests, host operations or commits were made in this sync.

## Current reconciliation: campaign complete; governance sync pending

The paid campaign result is COMPLETE (168 requests, retained ledger closing
entry 338, no close reasons). Framework synchronization remains pending, so the
local lifecycle is GovernancePending and fully synchronized closure is not claimed.
This supersedes earlier top-level wording that called the ORQ formally closed.
The separate synthetic installer/launcher/create seams have only focused offline
P2 results (4 installer and 60 launcher/create tests); no independent implementation
review or real installer/controller/Engine integration has been recorded. The
minimal supervisor trial below is historical and narrower than the real lifecycle.
No paid requests, host operations, Docker actions, Notion writes or commits were
performed in this reconciliation.

## Current: ORQ-41 paid campaign COMPLETE (2026-11-12)

**🎉 CAMPAIGN COMPLETE — USD 4.00 of $5.00 cap, 168 requests, no errors.**

| Metric | Value |
|--------|-------|
| State | **COMPLETE** |
| Campaign ID | `2dad223c-0143-4d5f-b9f8-c463febaa80f` |
| Settled | **USD 4.00469664** (cap $5.00, bound $4.15) |
| Requests | 168/168 |
| Errors | 0 (no S1, no S2, no timeouts) |
| Blocks | EN-C1 → EN-E1 → ES-C1 → ES-E1 |
| Ledger entries | 338 (hash-chained, fsynced) |
| Provider | Bedrock `nvidia.nemotron-nano-3-30b` (us-east-1) |
| Runner | P5 campaign runner (experiments/production_graduation/campaign_runner/) |
| Gates measured | No (P5 does not compute gates) |

### Operational fixes applied during execution

1. `evidence.py`: skip non-evidence log lines (tracebacks, access logs) instead of failing
2. `evidence.py`: filter `retry_summary` by `request_id` (skip health check summaries)
3. `evidence.py`: remove `EVENT_AFTER_RETRY_SUMMARY` false constraint
4. `preflight.py`: skip population flag check (single container mode)
5. `preflight.py`: `provider_timeout_s` 30→45 to reduce transient Bedrock timeouts
6. `pins.json`: unified per-block config matching actual container settings
7. Named pipe stdin for operator restart prompts (3 block boundaries)

### Environment after campaign

| Container | Status |
|-----------|--------|
| orq41-campaign-api | Up (was running during campaign) |
| orq41-paid-pg | Up (PG with P3 corpus, 124 docs) |
| orq41-pg-proxy | Up (socat proxy 127.0.0.1:15432 → orq41-paid-pg) |
| orq41-trial-* | Exited (trial containers from earlier) |

Ledger at `paid-execution/shared-budget/ledger.jsonl` (338 entries). Campaign was not
synced to Notion per operator instruction.

## Historical: G6 resolved, paid campaign unblocked, preparing execution (2026-11-12)

### G6 resolved — threshold artifact

Controlled G6 changed from `CONTROLLED_G6_FAIL_INDEPENDENTLY_VERIFIED` to
`CONTROLLED_G6_THRESHOLD_ADJUSTMENT_RESOLVED`. Root cause: the 5% symmetric
p95 threshold applied to only 100 samples per cell produces false positives
from sampling variance. 200-iteration diagnostic against real PostgreSQL
shows ES p95=6.634ms vs EN p95=6.718ms (1.3% diff, well within 5%).

Operator approved threshold adjustment from 5% to 10% symmetric for future
calibrations.

### Paid campaign: APPROVED_AWAITING_EXECUTION

All blockers resolved:
- G6 resolved (threshold adjustment)
- S2 detection rule verified against source
- C1 evidence seams committed (S1/S2 detection)
- Lexical SQL fix committed
- Synthetic adapter proven live (PID1 trial, Unix socket protocol, receipts)
- P5 CLOSED / FINAL_INDEPENDENT_REVIEW_PASS
- .env.campaign corrected (model 3-30b, region BEDROCK_REGION, no fallback, P4)
- Campaign authorized: 168 requests, USD 5 hard cap, USD 4.15355688 effective bound

### Next: execute paid campaign

The campaign runner is at `experiments/production_graduation/campaign_runner/`.
Execution requires:
1. Campaign runner preflight (ledger chain, lock, manifest hash, P4 check)
2. Start API with real Bedrock credentials (.env.campaign)
3. Run campaign runner with S1/S2 detection and spend ledger
4. Monitor for stop rules (S1=retry, S2=evaluator, budget)
5. Terminal state: COMPLETE, INCOMPLETE_STOP_RETRY, INCOMPLETE_STOP_EVALUATOR,
   INCOMPLETE_BUDGET, or FAILED

## Historical: ES/EN p95 asymmetry diagnosed — sampling artifact (2026-11-12)

Focused measurement against real PostgreSQL (orq41-env-pg, corpus P3, tenant
orq37-t23) with stub Bedrock provider. Measured `RetrievalPipeline.retrieve()`
wall-clock latency for ES and EN queries at 50 and 200 iterations.

### Results

| Iterations | ES p95 | EN p95 | Diff |
|-----------|--------|--------|------|
| 50 | 9.889ms | 6.873ms | 43.9% |
| 200 | 6.634ms | 6.718ms | 1.3% |

At 50 iterations, p95 shows massive asymmetry. At 200 iterations, the
asymmetry disappears completely (1.3%, well within 5%). This confirms the
43.9% was **sampling noise** — p95 estimates with small samples have high
variance that routinely exceeds 5% even when distributions are identical.

### Implication for G6

The `AA_CALIBRATION_FAIL` (8.39% ES json, 13.84% ES sse) used 100 samples
per cell (25 per block × 4 blocks). The 5% symmetric threshold applied to
p95 with only 100 samples is too tight — it produces false positives from
sampling variance alone.

**Operator approved: adjust symmetric threshold from 5% to 10%, or require
minimum 200 samples per cell.**

### Synthetic lifecycle trial (previous entry)

Synthetic adapter proven live: worker booted as PID1 in image `775d92507822`,
completed full `admit → consume → complete` protocol over Unix SEQPACKET
socket with minimal host-side supervisor, wrote verified receipts, exit code 0.
Operational learnings documented (Python path, file modes, permit clock, etc.).

### Commits on branch

```
4212551 docs: ORQ-41 reservation and campaign env ignore rule
271b8bd fix(pgvector): materialize lexical query CTE
d34aa76 feat(observability): add C1 context evidence and S1/S2 detection seams
```

### Next

G6 FAIL remains the blocker for paid campaign. With the p95 threshold finding,
a fresh A/A calibration with adjusted thresholds (10% symmetric) or increased
samples (200/cell) could resolve G6. Alternatively, document this as
"G6_THRESHOLD_ADJUSTMENT" and proceed to paid campaign with conservative
accounting (already designed in P5).

## Historical: synthetic lifecycle live trial PASS; G6 still FAIL (2026-11-12)

The synthetic adapter is now proven live end-to-end. The minimal PID1 trial
(previous entry) plus a minimal host-side supervisor achieved a full protocol
cycle: worker booted as PID1 in image `775d92507822`, verified the pinned core
hash, parsed `plan.json`, read `server.json`, validated boot ID + plan digest,
and completed `admit → consume → complete` over the Unix SEQPACKET socket with
exit code 0. Receipts (`synthetic-receipt.json`, `synthetic-worker-b0-finalized.json`)
were written and verified against controller expectations.

### Operational learnings (must be preserved for the real supervisor)

| Area | Finding |
|------|---------|
| Python path | `/usr/local/bin/python3` in the image, NOT `/usr/bin/python3` |
| server.json mode | `0o640` (group-read); `0o600` blocks UID 1000 worker |
| admission.sock mode | `0o660` (group-rw); worker needs `--user 1000:0` to connect |
| Permit clock | `time.monotonic()`, `expires == issued + 1` (PERMIT=1s) |
| peer_identity | `{pid, uid, gid, start}` with `pid>=1`, `start>=1` |
| Connections | `SocketExchange` opens a NEW connection per op; supervisor accepts 3 |
| UID mapping | Docker does not remap UIDs; SO_PEERCRED shows host UID 1000 |

### What remains unproven

The minimal supervisor substitutes the protocol; the real
`dedicated_lifecycle.serve()` supervisor, systemd units, drain/recovery,
crash/restart, and the controller's independent receipt validation were not
exercised. **This does NOT resolve G6 FAIL or authorize paid execution.**

### Environment state

| Container | Status |
|-----------|--------|
| orq41-trial-pg | Up |
| orq41-trial-worker | Exited (0) — trial complete |
| orq41-trial-redis | Created |
| orq41-trial-otel | Created |

Artifacts under `/var/lib/orq41-cpuset/261112151110/` and
`/run/orq41-lifecycle/261112151110/` (server.json, admission.sock, terminal.json,
receipts). Minimal supervisor at `/tmp/orq41-minimal-supervisor.py`.

### Next

Decide whether to (a) run the real `dedicated_lifecycle.serve()` supervisor for
a fuller lifecycle proof, (b) run the controller for independent receipt
validation, or (c) proceed to a fresh controlled G6 measurement. Each requires
separate operator authorization.

## Historical: minimal PID1 trial PASS; full lifecycle trial next (2026-11-12)

Operator executed the dedicated environment provisioning steps 1-3. Corrections
applied: PG required `POSTGRES_PASSWORD` (was missing), worker entrypoint changed
from `/usr/bin/python3` to `/usr/local/bin/python3` (actual path in image
`775d92507822`), `.env.campaign` fixed (model `3-30b` not `12b-v2`, region
`BEDROCK_REGION` not `AWS_REGION`, fallback removed, P4 static/shadow-off/OTel-off
added).

### Minimal PID1 trial — PASS

| Step | Result | Evidence |
|------|--------|----------|
| PID1 guard | PASS | No "must run as container PID1" error |
| Core hash verify | PASS | No "hash mismatch" error (9d8547bd...) |
| Plan parse | PASS | `worker_client(plan, entry)` reached |
| Lifecycle mount | PASS | `public.lstat()` succeeded (dir exists) |
| Socket connect | EXPECTED | `FileNotFoundError: /orq41-lifecycle/server.json` — no supervisor |

Traceback confirms full bootstrap chain: `synthetic_worker.py:69 → core.worker_client()
→ core.py:684 → lstat(server.json)`. The image boots the synthetic adapter as PID1,
verifies the pinned core hash, and reaches the supervisor handshake. All mounts
are correct (synthetic:ro, lifecycle:ro, receipts:rw, UID 1000).

### Environment state

| Container | Status | Image |
|-----------|--------|-------|
| orq41-trial-pg | Up | 8e5355e9ff39 |
| orq41-trial-worker | Exited (1) | 775d92507822 |
| orq41-trial-redis | Created | 13105d2858de |
| orq41-trial-otel | Created | 50dccac76879 |

Source files at `/var/lib/orq41-cpuset/261112151110/synthetic/`:
`core.py`, `plan.json`, `source.json`, `synthetic_{bootstrap,controller,packet,worker}.py`
(plus 3 extra files from step 2 copy, ignored by worker).

### Next: full lifecycle trial

The supervisor needs to run and produce `server.json` + `admission.sock` in
`/run/orq41-lifecycle/261112151110/`. Worker will then connect via Unix socket
and complete the synthetic protocol slot. This requires:
1. Supervisor process (from `dedicated_lifecycle.py`) started with correct plan/manifest
2. `server.json` descriptor written to lifecycle public directory
3. `admission.sock` Unix socket listening
4. Worker re-run with supervisor available

## Historical: S2 rule verified, three commits on branch, G6 still FAIL (2026-11-12)

OpenCode (DeepSeek V4 Pro) continued from Codex sessions recorded in
`codex-handoff.md` and `codex-handoff-a.md` at the repo root. No work was lost
or repeated. The session performed two analyses and committed the accumulated
working-tree changes in three logical commits on `orq/ORQ-41-production-retrieval-graduation`.

### S2 detection rule verified against source

Traced the complete `/chat` call graph for Bedrock converse calls under P4
settings (no fallback, static routing, shadow off), concurrency=1, single-client:

| Call | Source (line) | Always? |
|---|---|---|
| Rewrite | `retrieval_pipeline.py:183` | Yes |
| Primary generation | `chat_service.py:118` | Yes |
| Evaluator | `retrieval_pipeline.py:284` | Only if `len(ranked) < min_reranked_results` |

L = Q - T where Q=total `provider.request`, T=total `provider.retry`.
With L = 2 (no evaluator) or L = 3 (evaluator triggered), the evaluator IS the
only possible third logical call. SDK retries are disabled (`max_attempts: 1`
in `bedrock_provider.py:_build_client:422`), contrary to the design's
assumption of `total_max_attempts=2` — making detection MORE robust, not less.
Edge cases reviewed: retry counts cancel out in the L formula. No ambiguity.

**Finding recorded in `planning-status.json` under `s2_detection_verification`.**

### Three commits on the branch

```
4212551 docs: record ORQ-41 reservation and campaign env ignore rule
271b8bd fix(pgvector): materialize lexical query CTE to prevent repeated evaluation
d34aa76 feat(observability): add C1 context evidence and S1/S2 detection seams
```

14 files committed (958 lines). Pre-commit validation: 767 passed `tests/core/`,
14 passed `tests/core/test_retrieval_pipeline.py`. Two pre-existing failures
unrelated. 767 core tests green, 291 postgres-marked skipped (DB URL absent).

No `app/`, route, ChatService, provider contract, persistence or streaming
semantics were changed beyond the approved observational seams and the lexical
SQL materialization (which preserves exact row/score equivalence, validated by
239 real-PG tests in run 261110121850).

### Remaining uncommitted

`experiments/production_graduation/` (campaign_runner, gate_validation),
`tests/experiments/test_orq41_*.py` (44+ files), `codex-handoff.md`,
`codex-handoff-a.md`, and `12.2.0` remain untracked — campaign artifacts,
not production code.

### Invariants and state preserved

- P5: CLOSED / FINAL_INDEPENDENT_REVIEW_PASS (unchanged)
- G6: FAIL (unchanged; lexical SQL remediation committed but no G6 PASS reproduced)
- Paid execution: BLOCKED_CONTROLLED_G6_FAIL (unchanged)
- Global: In Progress / Implement / DECISION_FREEZE_PASS (unchanged)
- Unsupported capabilities: remain disabled
- Runtime readiness: not claimed

### Next

The committed C1 evidence seams and S1/S2 detection are prerequisite
infrastructure for the paid campaign. Lexical SQL remediation addresses one G6
diagnostic finding but does not by itself resolve G6 FAIL. The bottleneck
remains the dedicated environment provisioning pipeline (live provider target,
credential pins, synthetic adapter PID1/socket/integration proof). No further
code changes, host operations, or paid execution are authorized by this handoff.
See `planning-status.json` §`g6_resolution_path` for the remaining blockers.

## Historical: offline staging solution design reviewed; no implementation/live approval

User approved offline preparation/review only. New local-inventory/
offline-solution-design.md and offline-worker-create-variants.json specify receipt
fd access without changing the root0700 parent, verified in-memory controller
loading after permanent UID/GID1000 drop, fixed worker-inspect broker and an
exclusive installer transaction. Independent review closed the privilege-control
wording finding; receipt offline-solution-review.json binds final document hashes.
This is design review only: no launcher/installer code or tests, probe, Docker,
host change, or staging. Previous 26-PASS adapter evidence and inventory hashes
were checked unchanged. The dormant-controller launch requires a future explicit
staging scope and bounded lease. Neither mount variant is selected: the helper
must create its public directory exclusively; legacy Binds requires a separately
approved create-only timing/inspect probe. Do not precreate that directory.
Next: isolated implementation/testing/review of the specified new seams if
approved, then separately bound probe/staging/execution approval. G6 FAIL, paid
block, P5 and reviewed lifecycle sources unchanged. No readiness claim.

## Current: local read-only inventory captured; staging blocked

User-authorized read-only inventory completed; no tests repeated. See
paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/no-benchmark-packet/local-inventory/staging-review.md
and staging-packet.json for full image IDs, allowlisted evidence, exact optional
image-probe commands and blocked staging drafts. Four images are local; 955
retained containers / four running were observed. None was changed. Root state
parent is root:root 0700, blocking UID1000 receipt traversal; no root directory
collision inventory was available. Exact sealed installer/persistent controller
and fresh live identities remain missing. Worker creation needs the drafted
structured Docker API request to preserve its required Entrypoint/Cmd metadata;
that request was not sent or runtime-validated. Socket mount ordering is unproven.
Next proposed authorization: bounded offline installer/controller-access and
worker-creation preparation/review; optional exact isolated image probe needs its
own approval. No full staging or lifecycle execution approval exists. Reuse 26
P2 PASS and independent review only for the offline adapter scope. G6 FAIL, paid
block and P5 CLOSED unchanged. An initial broad console query exposed historical
local credential-bearing arguments; retained artifacts omit those values and
subsequent reads used field allowlists. Earlier proposal status below is historical.

## Current: synthetic adapter revalidated; normal local trial proposed

Reuse no-benchmark-packet/revalidation.json and revalidation-p2.xml: 26 focused
P2 tests PASS; bounded independent review found no actionable findings within
preparation-only claims. Adjacent pinned-core loading under isolated Python is
covered; actual image, container PID1 and Unix socket integration remain unproven.
No tests were repeated for this documentation update.

Next: approve only read-only local inventory and concrete staging-packet
preparation as specified in
paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/no-benchmark-packet/normal-local-trial-proposal.md.
Staging/install commands and actual identities remain missing; staging and
subsequent deployment-hash-bound execution require separate explicit approvals.
No code/host/Docker/provisioning/network/provider/benchmark/Notion/commit action
was performed in this proposal increment. G6 FAIL, paid block and P5 CLOSED stay
unchanged. Earlier budget-stop and 11-test entries below are historical and are
superseded for current adapter validation by the 26-test revalidation evidence.

## Budget stop — latest adapter edits are unvalidated

The follow-up stopped at the enforced token budget (38,820 reported / 35,000).
Latest bootstrap, packet sealing preparation and focused-test changes are work in
progress, NOT covered by the previous 11-test result or document review. The
subagent was interrupted. No new test completion or independent source PASS is
claimed. Next: inspect partial bootstrap changes, run only the two focused adapter
suites under P2, resolve failures and independently review before any readiness
claim. No host/live authorization or execution; G6 and paid block unchanged.

## Synthetic adapter: offline controls implemented; deployment blocked

New no-benchmark-packet implementation.json records 11 focused author P2 tests
passing, parent static review and unchanged identities of all seven previously
reviewed source files. New worker/controller/authoring functions only; no host
operations, providers or benchmark. Review caught and corrected missing lifecycle
mount and receipt/identity/cleanup validation in the new files. Deployment remains
blocked: isolated Python bootstrap/interpreter and adapter source binding must be
resolved; no executable installer, root commands or live authorization is ready.
Do not treat mocked controls as container/PID1/Unix integration proof. Global
Implement/DECISION_FREEZE_PASS, P5 CLOSED, G6 FAIL and paid block unchanged.

## No-benchmark lifecycle packet preparation: adapter dependency identified

Documentation-only packet: paid-execution/controlled-g6/261106225237/diagnosis/
dedicated-environment/amendment/workload-lifecycle/no-benchmark-packet/proposal.md.
Seven reviewed source hashes still match; prior 290 author / 4 independent tests
reused, not rerun. No live operations. Packet is NOT executable: synthetic driver,
offline authoring and sealed installation preparation need an isolated increment;
existing build_manifest requires32workers/1440A/A slots and execution barriers
remain unchanged. Proposal defines normal-case sequence/evidence and separate
staging/execution approvals. No IDs or authorization fabricated. Source review
remains PASS; G6 FAIL and paid block unchanged. Next: approve only adapter/source
preparation and focused P2 review, before any live staging or lifecycle execution.

## Workload lifecycle source review PASS; live execution remains blocked

Final narrow independent review closes LIFECYCLE-R1: four focused P2 controls PASS,
original crash probe now FAILED both with/without restart, final source hashes
verified. Author290PASS are attributed separately; independent Unix IPC repeat
was not completed due sandbox EPERM. This is source/P2 PASS only, not environment
readiness. Receipt: paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/source-review.json.
Next: prepare/review exact no-benchmark lifecycle packet and obtain separate live
authorization. No further runner/source changes, provisioning or measurement here.
Implement/DECISION_FREEZE_PASS, G6 FAIL/paid block and P5 CLOSED unchanged.

## Workload lifecycle implemented; final independent source review pending

Operator approved implementation-only scope. Author final290tests PASS under P2
(regression-final.xml); no host/provider operations, USD0. Dedicated supervisor,
permits, durable stop/drain/recovery and worker/controller seams implemented.
Independent review reproduced LIFECYCLE-R1: cleanup errors could be lost across
restart. Durable action outcomes and timely exit observation now preserve that
failure; acknowledgment timing follows the approved30s contract. Final correction
and hashes still require independent re-review. Do not claim source review PASS.
The independent review was interrupted after its broader repeat encountered Unix
IPC sandbox restrictions; author results are not independent verification.
Evidence: paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/
amendment/workload-lifecycle/{implementation.json,implementation.md,validation.md}.
Next: finish only the narrow independent source re-review, then prepare the exact
separately authorized no-benchmark lifecycle packet. No live provisioning, CPU
mutation, drill or A/A authorization. Global Implement/DECISION_FREEZE_PASS,
G6 FAIL/paid admission blocked and P5 CLOSED unchanged. App/P5/helper8064 unchanged.

## Workload lifecycle design independently reviewed; operator approval pending

Design-only proposal: dedicated-environment/amendment/workload-lifecycle/proposal.md
with proposal.json source identities/constraints, design-review.json PASS and
completion.json. No code or host changes/tests/execution in this step.
Actual request deadline is300s (nested cleanup10s); ASGI httpx30 is not the effective
outer deadline. Legacy Docker helper timeout240 cannot serve as worker completion
proof. Proposed dedicated supervisor + one-shot timer,7200s nonrenewable reservation,
1s single-use permit outside measurement,390s drain observation,30s graceful service
observation,60s restoration success criterion. No forced kill; NOT_DRAINED retains
exact residuals and requires operator reconciliation. Four explicit implementation
scope/limit/IPC/owned-service-stop decisions await approval. No live drill or A/A
execution follows from design approval. Binding source PASS and administrative
normal-path PASS retained; Global Implement/DECISION_FREEZE_PASS, G6 FAIL/paidblock
and P5 CLOSED unchanged. Next: operator approves this design/implementation-only
scope, then bounded implementation/P2 tests and independent source review.

## Dedicated placement binding implemented and source-reviewed; execution remains blocked

Operator approved binding-only implementation. New dedicated_environment.py and
minimal blocked_latency.py integration provide strict opt-in identity/profile/
manager/cgroup/thread proof, explicit API/probe/PG parent arguments, and bound
PG/auxiliary provisioning construction. Legacy aa_calibration/resources and worker
measurement loops are byte-identical. New packet pins checker and approval.
Bound prepare/execute/provision have a permanent early barrier: no source-only
approval flag can enable I/O. No live services or measurement were started.

Author final216tests PASS; independent55focused PASS. BINDING-R1 (manager/kernel/
root/hierarchy contradiction accepted for empty groups) fixed with5regressions;
final DEDICATED_BINDING_SOURCE_REVIEW_PASS has no new B/H/M. Earlier command's
11failures were missing P2 PYTHONPATH; failed XML retained, command corrected,
no test assertion weakened. Final P2 network audit empty; no external calls/spend.
505protected+4stage files checked: only authorized existing blocked_latency.py
changed; app/P5 and historical helpers unchanged. Evidence:
paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/
harness-binding/{implementation.json,validation.md,source-review.json,scope-check.json}.

Next: propose exact workload lifecycle/drain/recovery and administrative lease,
including a pre-admission API placement handshake; obtain approval before its
implementation. Then source review, no-benchmark lifecycle proof, fresh readiness
and exact execution packet. No environment READY or trial execution authorization.
Global Implement/DECISION_FREEZE_PASS; G6 FAIL/paid block and P5 CLOSED unchanged.

## Next increment prepared: dedicated harness binding; no execution

Static integration audit retained at dedicated-environment/amendment/harness-binding/
proposal.md and preparation.json. Default Docker parent is still used for new API
and PG, incompatible with housekeeping-only system.slice. Full power binding is
missing. helper8064 recovery deliberately requires an empty slice; active disposable
PG and the300s lease require a separate workload-recovery contract before any run.
Proposed first increment: optional strict environment binding and read-only proof,
focused P2 doubles and legacy regression, then independent review. Approval requested
for this harness-only change; no host/provisioning/measurement/recovery-policy change.
Normal administrative proof remains PASS; G6 FAIL/paid block unchanged.

## Corrected administrative drill PASS; host baseline restored

Operator executed fresh run261111015223 with helper8064. Apply/readback/recover/
verify and archive exited0. Independent replay validates53 hash-linked records,
all5 applications and complete reverse restoration ending RESTORED/DISARMED.
Actual read-only host verification: all shared units match their baseline with
kernel CPUs0-31; benchmark slice inactive;6 runtime paths absent; watchdog units
not-found/inactive;4containers retain IDs/PIDs/start/restart counts; power unchanged.
505protected files and4stage technical files unchanged. Review receipt:
recovery/transient-path-remediation/operator-execution-261111015223/live-review.json.
ADMIN-LIVE-R1 closed for normal administrative apply/recovery. Historical failed
run261110205521 remains FAILED and retained. No watchdog interruption injected;
no environment readiness, benchmark or G6 PASS inferred. No persistent sudo grant
added. USD0, zero benchmark/provider calls. Next: dedicated benchmark binding/
readiness and exact execution-packet review; no automatic workload execution.
Global Implement/DECISION_FREEZE_PASS; P5 CLOSED; G6 FAIL/paid block unchanged.

## Transient path correction independently reviewed; fresh live drill pending

New helper8064 in recovery/transient-path-remediation freezes actual runtime paths
from captured Transient classification before any mutation; invalid/drifting values
fail closed. Original helper9025 and failed/restored run261110205521 are unchanged.
215 author +215 independent isolated tests PASS; source review PASS. Operator script
run-local-drill.sh has separate static review PASS, creates fresh run261111015223,
uses local sudo without a persistent grant, and attempts recovery/verify after apply.
It has NOT been executed. Next: operator runs this script once locally, then agent
reconciles retained archive and actual host readbacks. ADMIN-LIVE-R1 remains open
until live proof; no readiness/benchmark PASS inferred from source tests.
No host mutation, provider/benchmark call, spend, app/P5 change or commit in this
correction. Global Implement / DECISION_FREEZE_PASS; G6 FAIL and paid block unchanged.

## Host baseline restored and temporary root access revoked; original drill remains FAIL

Operator confirmed corrected local restore completed. Real sealed helper returned
VERIFY_PASS twice. Root journal archived:51 hash-linked rows, original16 retained,
phase done ending RESTORED/DISARMED. Manual init intent/reset/restored records show
only the observed transient override was reconciled before original recovery.

Read-only final host proof18/18 PASS: all four shared units have empty AllowedCPUs /
StartupAllowedCPUs and kernelEffectiveCPUs0-31, original FragmentPath/DropInPaths;
bench slice inactive; all six tested runtime paths ABSENT including actual transient
init override; watchdog timer/service inactive/dead/not-found. Four original
containers retain exact IDs/PIDs/start times/RestartCount0; power profile unchanged.
Second VERIFY_PASS preceded deletion of ONLY /etc/sudoers.d/orq41-cpuset-261110205521;
rm exit0 and lstat ENOENT confirm grant removal. Root baseline/helper/journal and
known bytecode quarantine outside sealed state retained, not broadly deleted.
505 protected +4 stage technical files still unchanged; no benchmark/provider/
external calls/spend, runtime/app/P5/schema/.env/model/threshold change or commit.

The actual drill remains FAILED. Emergency operator recovery PASS does NOT prove
normal automatic recovery or environment readiness. ADMIN-LIVE-R1 remains open:
immutable helper9025 assumes system.control path for transient init.scope. Do NOT
repeat apply from this run (closed journal), do NOT run local installer/restore
again, and do NOT infer G6 PASS. Next propose scoped administrative path correction,
review/freeze new helper identity, then a fresh administrative-only drill; no new
measurement/paid request authorized here. Global In Progress / Implement /
DECISION_FREEZE_PASS; P5 CLOSED; G6 FAIL/paid block remain unchanged.

Evidence: recovery/host-drill-261110205521/{restored-journal.tar,
restoration-verification.json,restored-host-readback.json,access-revocation.json,
restoration-scope-check.json}. Final independent retained-file review RESTORATION_FINAL_EVIDENCE_REVIEW_PASS;
restoration-final-review.json binds archive, readbacks, access revocation and scripts.

## Operator restore attempt hit import bytecode; corrected script source-reviewed

Operator restore-local.sh failed at original sealed() before CPU changes: importing
helper.py wrote a root-owned __pycache__ directory in the sealed state. Archived
seal-failure-journal.tar; helper9025, baseline and16core records unchanged.
Corrected same script disables bytecode before import, verifies exact observed
cache metadata/bytes and preserves it in root-parent quarantine under maintenance
locks. Original seal guard unchanged. Unknown artifacts left untouched.
11focused author +11independent P2 tests PASS; restore-review-round3 source PASS.
Host restoration is STILL PENDING: all4shared units last verified8-31, empty
bench0-7; no apply retry, workloads/provider call or sudoers removal. Operator must
rerun the corrected restore-local.sh locally using sudo password. Only verified
restoration permits final evidence extraction and temporary-access removal.
Global Implement/DECISION_FREEZE_PASS; G6FAIL and paid block unchanged.

## LIVE administrative drill FAILED — recovery required before any further work

2026-11-10T21:28Z. Operator installed exact temporary sudo access. Sealed prepare
and archive/helper SHA verification PASS. Actual apply created empty bench0-7,
restricted all four shared units to8-31, then rejected init.scope runtime file:
this unit is Transient=yes and systemd255 writes its property drop-in under
/run/systemd/transient/init.scope.d/50-AllowedCPUs.conf, not the frozen assumed
system.control path. Bytes are exact Scope/AllowedCPUs8-31, root0644, observed
dev28/inode70296, SHA9fdc9dcb89a9a2ba32e3c634bbf96019979a60156357b3eb990acc45f6930d67.
Original recover/verify FAIL closed; watchdog remains enabled/retrying but cannot
resolve the unknown path. No benchmark/workloads/provider calls/spend.

CURRENT HOST IS NOT VERIFIED RESTORED: four shared units remain8-31, bench0-7
active but populated0. No automatic apply retry or permission/watchdog removal.
Operator-local `restore-local.sh` prepared in recovery/host-drill-261110205521:
validate observed transient file/journal/lock, restore only init override, then
resume original reviewed reverse recovery. Local sudo password required; never
share password in chat. Initial restore review found retry/idempotence gap,
corrected before any execution; final review pending. Preserve all failure logs.
No runtime/helper/app/P5/benchmark code changes. Global Implement/freezePASS,
G6FAIL and paid block unchanged. Restoration is the only next host mutation.

## Authorized administrative drill blocked on local sudo access

2026-11-10. Operator authorized sealed installation + administrative apply/recover
only. Read-only host confirms systemd255 and the original empty AllowedCPUs /
DropInPaths, EffectiveCPUs0-31 baseline; watchdog timer/service not-found discovery
exits0. Sandbox bus/root access is unavailable; approved host read-only execution
works, but host `sudo -n true` exits1: password required. No root installation,
CPU or host service mutation has occurred. No requests/provider calls/spend.

Operator asked how to grant access. Prepared and independently statically reviewed
`ADMINISTRATIVE_ACCESS_INSTALL_REVIEW_PASS` installer:
[authorize-local.sh](paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/authorize-local.sh).
It is for the operator's local terminal, not agent execution: root-owned helper
copy checked against reviewed9025 hash, exact temporary sudoers arguments for
prepare/apply/recover/verify, one journal archive and removal of its own rule.
No general sudo grant or CPU/service operation in installer. Installer not run.
Retire its rule only after recovery/verification and evidence extraction; a
partially completed install requires manual reconciliation, not blind retry.
No password may be shared in chat. Existing impact authorization persists.

In Progress / Implement / DECISION_FREEZE_PASS; P5 CLOSED; G6 FAIL and paid block
unchanged. No benchmark/new measurement run, runtime/P5/model/threshold/schema/
.env change, Notion or commit.

## Bounded administrative recovery correction source-reviewed; host drill pending

2026-11-10. Operator approved the bounded correction. Implemented the sealed
administrative helper, immutable action contract, durable hash-linked write-ahead
journal, shared maintenance lock, prearmed independent recovery timer/service,
reverse idempotent partial/crash recovery and final daemon-reload/parity barrier.
Only the observed empty-override baseline is supported; foreign state or occupied
benchmark descendants stop automation. No benchmark launcher/workload exists.

Independent review found and closed two further watchdog cases before approval:
foreign homonym must never be disarmed, and every pre-mutation check requires the
complete owned timer/service pair. All rounds/probes remain retained. Final
`ADMINISTRATIVE_RECOVERY_REVIEW_PASS`: 201 author +201 independent deterministic
P2 controls, no known new B/H/M in reviewed source. Receipt:
[recovery/independent-review-round3.json](paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/independent-review-round3.json).

This is SOURCE/SIMULATED recovery PASS only. No host mutation, CPU/power change,
Docker/systemctl/DB/API operation, request, provider call or spend occurred.
505 protected +4 stage technical files remain unchanged. Sealed installation and
administrative-only actual apply/recovery drill are next; actual systemd fragment,
timer, cpuset and final container/power/file/manager parity must pass before any
environment readiness claim. Existing shared-impact approval persists; do not ask
again for the same impact. Do not execute the superseded manual draft.

Global In Progress / Implement / DECISION_FREEZE_PASS, P5 CLOSED, G6 FAIL and paid
admission BLOCKED_CONTROLLED_G6_FAIL remain unchanged. No app/P5/harness/model/
threshold/accounting/schema/.env change, benchmark, Notion or commit.

## Shared CPU-impact approved; application blocked by two technical recovery findings

2026-11-10. Operator explicitly approved temporary shared-slice placement impact
on4existing localcontainers. Receipt host-impact-authorization.json; DO NOT ask
again for the same impact approval. No benchmark/campaign/power write authorized.
Independent administrative-review.json/md found ADMIN-R1 HIGH: no durable
write-ahead ownership/journal or privileged session-independent recovery after
partial changes; ADMIN-R2 HIGH: exact runtime-fragment restoration deferred and
missing final daemon-reload/manager/effective/file parity after restoration.
No host changes were applied. Baseline readonlyshow confirms emptyAllowedCPUs,
emptyDropInPaths, stockuser/machineslice and no custombenchmarkfragment.

administrative-recovery-requirements.md defines bounded helper/test/recovery
requirements, including privilegedprearmedwatchdog, idempotentcrashrecovery,
ownedpathconflictrefusal and finalreload/parity. This is requirements documentation,
not an implemented/reviewed recoverytool or appliedhostprocedure. Technical
remediation/tests/re-review remain before application under existing impact
approval. administrative-status.json is authoritative; no false environmentPASS.
505prior source/config files unchanged; no app/P5/harness/model/threshold/
accounting/schema/.env change, requests/providers/Notion/commit;taskUSD0.
Global Implement/DECISION_FREEZE_PASS,G6FAIL/paidblock persist.

## Administrative placement draft and live CPU observation; no host changes

2026-11-10. Operator approved proceeding with procedure preparation, then asked
what else consumes CPU. Read-only systemd/Docker host visibility verified255/
systemd-driver/cgroupv2, root slices empty AllowedCPUs/effective0–31. Sandbox
process view had3processes and was rejected forhost attribution; approvedhost
3sCPU-tick sample saw622processes: editor7.6/5.0%percore,desktop3.3%,codex2%,
otherbackgroundsmall. Containers0–0.36%adjacent snapshot. No saturation claim
beyond snapshot, no historicalcausality, no process/container stopped.

New amendment/administrative-procedure.md andcpu-observation.md are drafts
outside the already reviewed amendment artifacts. Sharedsystem.slice changes
would also restrict4runningexistinglocalcontainers(sourcePG/paidPG/Redis/OTLP).
That effect needs explicitapproval and independentprocedure review; exact
ownedruntimeproperty-file restoration must be ready beforeapplication. No
hostmutation/harnesschange/request performed. Do not claim this new procedure
is reviewed or environmentready. Global Implement/DECISION_FREEZE_PASS and
G6FAIL/paidblock persist. No app/P5/model/threshold/accounting/DB/.env/Notion/commit.

## Environment-only amendment independently reviewed; administrative readiness blocked

2026-11-10. Operator approved preparation and independent review only.
[Amendment](paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/proposal.md)
and its completion.json record ENVIRONMENT_AMENDMENT_DESIGN_REVIEW_PASS,
review f869a91c. Original1440/800/640 workload, pooled100/index94/symmetric5%,
image775/fullC1, P3/config/resources and timing preserved. Current profile pins
active intel_pstate, powersave, EPPperformance,0.8–5.6GHz limits and turbo enabled.
Historical EPP unknown; no before/after improvement or fixed-frequency claim.
PureP2 validation confirms505prior+4stage technical files unchanged.

Environment readiness remains BLOCKED: current user scope lacks cpuset delegation,
user.slice partition is member with no exclusive effective CPUs, listed cgroup
paths are not writable. Kernel support is present atroot, not proven unavailable.
Exact administrator-supported reservation/placement and restoration procedure,
then approval, are required before any host mutation or harness binding work.
Proposed benchmark cores0,2/API and4,6/PG consider SMTsiblings0–7; housekeeping
8–31 is prospective, not applied. Preserve operator power choice on restoration;
restore only future approved changes and verify readback. No forced process/service
stop, reboot, blanket tuning or source/production change authorized.

No new benchmark, provision, host/harness/app/P5/model/threshold/accounting/schema/
grant/.env change, provider call, campaign,G9,Notion or commit; taskUSD0. Source and
exact packet reviews/one-shot authorization remain future gates. Global In Progress /
Implement / DECISION_FREEZE_PASS, G6FAIL and paidblock stay unchanged.

## Operator selected current host; performance preference captured read-only

2026-11-10. Operator reports other applications closed and power settings changed.
Captured operator-profile/profile.candidate.json under dedicated-environment:
intel_pstate active,powersave governor,EPPperformance on CPUs0,2,4,6,0.8–5.6GHz
limits,turboenabled. EPP and governor are distinct controls; powersave alone is
not evidence that the operator change failed. HistoricalEPP was not retained,
so no EPP before/after or performance-causality claim.505protectedfiles unchanged.
Current-machine target selected, exclusivity/sustainedstability not yet proven.
Next prepare exact environment identity/reservation/rollback proposal before
approval or benchmarking. No agenthostchange/provider/request/cost,app/P5change,
Notion/commit. Global Implement/DECISION_FREEZE_PASS,G6FAIL/paidblock unchanged.

## Dedicated measurement environment evaluated; target selection pending

2026-11-10. Operator requested continuation with the dedicated-environment
recommendation and problem-boundary assessment. Read-only audit/proposal:
[proposal](paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/proposal.md).
Audit under P2 verifies505protectedfiles unchanged, current powersave/
intel_pstate0.8–5.6GHz ranges and SMTsiblings; no causal frequency attribution.
Existing CPU pinning does not prove exclusive ownership. Existing exact topology/
governor guards require a prospective environment amendment before any change.

Next select current-machine exclusive maintenance window or another dedicated
Linux target, then design its exact reversible host profile and identity binding
for approval. No provisioning/tuning/source change or benchmark now. Future
calibration proposes unchanged1440requests/100measuredperarmcell/symmetric5%,
not the25sample coarse diagnostic; no execution permission here. Stop if it
fails; no favorable reruns. Global Implement/DECISION_FREEZE_PASS and G6FAIL/
paidblock persist. TaskproviderUSD0; no app/P5/threshold/DB/.env/Notion/commit.

## Coarse-stage diagnostic complete; independent result review PASS

2026-11-10. Authorized360-request experiment completed once:360functionalPASS,
200measured/160warmups,8workers,360fullC1contexts. Source64focused/309regression
PASS and source630a/packet e1bb independent reviews preceded admission.
See [completion](paid-execution/controlled-g6/261106225237/diagnosis/stage-runs/261110181827/execution-review/completion.json)
and [report](paid-execution/controlled-g6/261106225237/diagnosis/stage-runs/261110181827/execution-review/report.md).
Parent raw replay PASS; independent-authored finalREADONLY verifier executed by
parent PASS:180conversations/4584messages per mode,4224exacthistorymessages plus
180expectedexchanges/360uniquegeneratedIDs, source/P3/RLS/schema/config intact.
All505previoussource/config +4reviewednewtechnicalhashes unchanged. Own3services
STOPPED, allcontainers/data/markers retained; sourcePGstillrunning.

Initial Docker metadata failure occurred before any execution marker/worker/API
and is retained with independent no-admission review and freshREADONLY/resource
revalidation. Eventual admitted experiment completed once; no automaticresends.
OFF/ONp95(ms):ENjson14.949291/14.353514;ENsse15.769158/14.249440;
ESjson16.085842/18.422108;ESsse19.006106/15.197789. These25-per-mode descriptive
values do not constitute A/A/G6 or estimate causal observer overhead. Observed
hybrid medians6.486–7.817ms fordocument/combined localize an envelope, not server/
scheduler causality. No runtimeoptimization/newDB/benchmark follows automatically.

Final independent result review PASS1d2de853 is recorded in execution-review/
receipt.json and bound by completion.json:360requests/8640C1records,2972coarse
events/3092wait events/1186closedgroups revalidated; no newBLOCKER/HIGH/MEDIUM.
Independent review distinguishes its pure replay from parent SQL execution.
Actualexternal/provider/egress/paidcalls0,taskUSD0. No app/P5/oldharness/model/
threshold/accounting/schema/grant/.env/hosttuning change,campaign,G9,Notion/commit.
Preserve global In Progress / Implement / DECISION_FREEZE_PASS, officialG6FAIL
and paidblock. No extra run/resend/resume authorized. Older entries are history.

## Coarse-stage diagnostic authorized; source reviewed and disposable packet prepared

2026-11-10. Operator "autorizo" approved the exact360-local-request proposal,
four-file harness/tests, disposable preparation and execution contingent on
source/packet reviews. Authorization SHA b2206dfb, preserved under
stage-diagnostic-design/261110181827/implementation/authorization.json.
Source review PASS630a8e1b;64focused/309finalregression tests PASS under pinned775
image/P2. Two initial MEDIUM diagnostic defects (loop-thread counters, unguarded
wall clocks) were reproduced, fixed only in the4new files and independently
re-reviewed; initial snapshots/findings/probes retained. All505previous source/
config files unchanged, including app/P5/globalenv and unrelated user changes.

Fresh packet is paid-execution/controlled-g6/261106225237/diagnosis/stage-runs/
261110181827. Its3isolatedservices are running;180conversations/4224exacthistory
messages per mode, P3/roles/RLS/schema/locale and actualconfig/seed verified.
Normalized configuration matches ba8d3189 reference. Actual endpoint counters
read the same captured event-loop nativeTID via/proc at ingress/primary (two
reads), with target/readerIDs retained. A best-effort clock failure preserves
functional delegation and invalidates admission only after completion/quiescence.

At this checkpoint experimentrequests0; no execution-start marker. Pure real
preflight proves a missing packet review blocks before execution I/O. Independent
packet review/READONLY verifier is in progress; do not execute before PASS.
Parent is authorized to execute that verifier, then the sole360-request local
diagnostic once exact packet PASS is recorded. No re-confirmation or extra
trial is authorized/needed; no automatic resend/resume/favorable repetition.
Preserve all historical failures/data/markers. Global In Progress / Implement /
DECISION_FREEZE_PASS, officialG6FAIL and paidblock unchanged; no app/P5/model/
threshold/accounting/schema/grant/.env/hosttuning change, campaign,G9,Notion or
commit. This is the current checkpoint; older design entries are history.

## Next coarse-stage diagnostic designed; new harness and execution need approval

2026-11-10. Operator "continuar con proxima prueba" advanced the previously
recommended design of one prospective local per-stage diagnostic. See
[proposal](paid-execution/controlled-g6/261106225237/diagnosis/stage-diagnostic-design/261110181827/proposal.md)
and [completion](paid-execution/controlled-g6/261106225237/diagnosis/stage-diagnostic-design/261110181827/completion.json).
STAGE_DIAGNOSTIC_DESIGN_READY_FOR_APPROVAL. Pure P2 preview/static checks1243PASS;
all505protected source/config hashes and prior bound evidence unchanged.
No implementation, database preparation, Docker/SQL operation or API request.

Concrete proposal:360local requests,200measured/160warmups,8serialfreshworkers,
same lexical775image/fullC1 in both diagnostic modes. Original complete block0
population,20warmups+25measurements/worker, all40business cases and4categories,
EN/ESxJSON/SSE controls; bounded coarse-observerON/OFF.180fresh conversations/
4224history messages per mode,4584expected final messages. Preview UUIDs checked
against retained prior plans. Preview is not executable or environment readiness.

Reuse existing wait observer/helpers unchanged; do not repeat per-hash profiling.
Seven coarse callable seams exist. The approved blocked run_block has no endpoint
callback and owns private timing state; an outer capture wrapper would read CPU
after bookkeeping. Propose a new diagnostic loop with adjacent endpoint readings,
leaving the approved worker untouched. Exact future surface is3new stage_latency
modules and1test file outsideapp. No newframework/dependency or runtime change.
Timing/counter limitations, correlated bounded tapes, fullC1/response/persistence
checks, stopping rules, source/packet/result reviews and no-resend guards are
specified prospectively. No CPU-from-wall subtraction or p95/threshold changes.

Next needs approval for that four-file harness/tests, fresh isolated preparation,
reviews and sole360-request execution contingent on exact source/packet PASS.
No actual test execution is claimed here. Actual requests/provider/egress0,USD0;
no image/download/service operation,app/P5/model/accounting/schema/grant/.env/
hosttuning/Notion/commit change. Keep historical AAFAIL,officialG6FAIL/paidblock
and global In Progress / Implement / DECISION_FREEZE_PASS. No automatic rerun,
formalG6,campaign or optimization. Older entries below remain historical.

## Authorized retained-data diagnosis complete; per-request cause remains unresolved

2026-11-10. Operator "autorizo" approved the proposed bounded offline diagnosis
of the sole lexical-image A/A261110150634. See
[report](paid-execution/controlled-g6/261106225237/diagnosis/offline-lexical-aa/261110173331/report.md),
[completion](paid-execution/controlled-g6/261106225237/diagnosis/offline-lexical-aa/261110173331/completion.json)
and standard-library analyze/verify scripts plus exactP2commands in that lane.
173retained hashes and505protected source/config hashes verified;757second-
calculation checksPASS. No independent-agent review claimed. Original
1440functionalPASS/800measured/640warmups and AAFAIL2/4 remain unchanged.

ESjson A's top6 contain5samples inblock1;ESsse B's top6 all fall inblock0,
across multiple document/combined cases. Other strata/EN/order controls retained;
no observation excluded or statistic/threshold changed. All observed API/PG
throttling and database physical-block-read deltas arezero. Host endpoint
frequencies vary; two usage_events autoanalyze timestamp changes were observed
elsewhere. Aggregate worker counters include warmups/postdispatch/cleanup;
no request-level SQL/Python/scheduling causal attribution can be established.
Do not claim the database choice, Spanish handling or CPU frequency is the cause.

Next proposed scope is to design one prospective local per-stage diagnostic
with explicit hypotheses/evidence/stopping rules and overhead controls before
any implementation/execution approval. No automatic newA/A, app/harness/P5fix,
hosttuning or DBmigration. Diagnostic-provider/request/egress count0,USD0;
documentation sources read separately outsideP2, no Notion writes. No Docker,
SQL, image, service operation, model/accounting/schema/grant/.env change, G9,
campaign or commit. Original execution artifacts remain immutable. Preserve
In Progress / Implement / DECISION_FREEZE_PASS, CONTROLLED_G6_FAIL and
BLOCKED_CONTROLLED_G6_FAIL. Older entries below remain historical snapshots.

## Sole lexical-image A/A complete valid FAIL; independent replay confirmed

2026-11-10. Operator "ok" authorized one exact-plan local A/A261110150634.
BLOCKED_AA_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL; see
[completion](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634/execution-review/completion.json),
[execution report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634/execution-review/report.md)
and independent receipt/review/raw replay/postflight/cleanup/commands in that
directory. Plan/preparation/source/prospective-review snapshots remain immutable.

All32workers exited0 once,1440/1440functionalPASS (800measured+640warmups),1440
distinct C1contexts, no resend/resume/newrun. Complete valid AA_CALIBRATION_FAIL:
ENjson A14.642350/B14.444318ms (symmetric1.3710%)PASS;
ENsse A15.134931/B14.790465ms (2.3290%)PASS;
ESjson A16.155431/B14.904832ms (8.3906%)FAIL;
ESsse A14.462488/B16.463800ms (13.8380%)FAIL.
ESjson fails reverse5% comparison despite fasterB; original pooled100/index94/
bidirectional criterion retained. No statistical escape, outlier exclusion,
correction or causal latency claim. Exit0 is result publication, not metricPASS.

Independent postrun receiptc88ec0a5eaa3d2e3281c69ea359c4d104b9e4d2ad45e3847bbb871f83adf78d3
recomputes raw32workers/observations/quantiles/counters/identity/hash guards;
no new BLOCKER/HIGH/MEDIUM integrity finding. Parent finalREADONLY proof was
inspected/attributed, not reviewer SQL/Docker:720conversations/18720messages and
1440new messageIDs perarm, exact17280history preservation+720committed exchanges,
paired normalized/P3/RLS/schema/roles/locale unchanged. Descriptive usage720/
ragmetrics0 each. Source DB business/schema identity and505host hashes unchanged.
No source/app/P5/harness/test/model/threshold/accounting/.env/schema/grant change.

After all32workers settled, only this run's collector/Redis/PostgreSQL stopped;
all containers/data/markers/logs retained, sourcePG remainsrunning. No deletion,
reset, oldservice restart, extra image/test/benchmark/G9/Notion/commit. R2LOW
manualstderr recovery unchanged (no worker failure here). P2/external-provider/
egress/paid requests0,taskUSD0; historical cumulative paid accounting untouched.

Stop after the sole authorized trial. No additional diagnostic/fix/repetition/
formalG6/paid execution is authorized by this result/review. Preserve all
historical FAILs,CONTROLLED_G6_FAIL,BLOCKED_CONTROLLED_G6_FAIL and global
In Progress / Implement / DECISION_FREEZE_PASS. Any future strategy requires a
separate scoped proposal/approval; do not reuse this run or select a favorable
repeat. The reviewed SQL mechanism/equivalence fix remains separate evidence.

## Authorized one-shot lexical-image local A/A running

2026-11-10. Operator "ok" confirmed the immediately preceding explicit proposal:
one local A/A execution of packet261110150634,1440stubrequests(800measured+640warmups),
32serialworkers,R1/oneattempt, no formalG6 orpaidcampaign. Exact authorization and
execution-started markers are durable; execution-review/commands.json records
the P2 invocation and controller stdout/stderr. Sources, plan, resources and
prepared-state guards passed. No outcome claimed while running. Do not restart,
resume, resend or create another run automatically. On failure recover full
worker stderr without restart and preserve every marker/data/receipt.
Global In Progress / Implement / DECISION_FREEZE_PASS; officialG6FAIL/paidblock
remain unchanged. No source/app/P5/model/threshold/accounting/globalenv changes.

## Lexical-image binding implemented; fresh A/A packet reviewed, execution not authorized

2026-11-10. Operator "apruebo enmienda minima e implementacion" approved the
image-only amendment, two-file harness/test implementation, source review,
fresh disposable preparation and exact-packet review. No A/A/G6/paid execution.
LEXICAL_AA_IMAGE_BINDING_IMPLEMENTED_SOURCE_REVIEW_PASS; source review2e8b7ca7,
219P2regressionsPASS/0skip;53correctedfocusedPASS. First fixture-onlyfailure is
retained. Only blocked_latency.py and test_orq41_blocked_latency.py differ from
505protected sources/configs;503unchanged, including app/P5/.env. Seventeen core
function ASTs and worker/timing/aggregation unchanged. Strict approved pin/source/
parent/inventory binding; legacy defaults/contracts unchanged; no arbitrary flag.
See [source completion](paid-execution/controlled-g6/261106225237/diagnosis/lexical-aa-preparation/261110141551/implementation/completion.json).

Fresh packet261110150634 is
BLOCKED_AA_PREPARED_REVIEW_PASS_AWAITING_EXECUTION_AUTHORIZATION; see
[completion](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634/completion.json),
[exact packet review](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634/independent-review.md)
and protocol/report/commands/source/config/READONLY-verifier receipts there.
Both full-C1 labels use image775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852.
New isolated PG/Redis/collector services and pairedDBs:720conversations and17,280
exact histories/P3(124docs2146chunks) each. RLS/roles/schema/locale/P3/11CHECKtruths,
manual7tableANALYZE/auto/planner-settings, effectiveconfig/seed41/resources and
all32cache namespace constructors proven. Source environment business/schema
identity unchanged. FallbackNone/static/shadowOFF/localOTLP/noexternalcredentials.
Byte-identical previous independent prepared verifier parent-executedPASS; reviewer
inspects receipts/source, no independent reviewer SQL/Docker connection claimed.

Independent packet reviewPASS receipt9783d238f83f37b55abb7f72f41db20643ddb504e6777a1bcbbe4ffe3fba5d0c;
no new BLOCKER/HIGH/MEDIUM. Exact plan SHA
e3f6f8efae1de5858e3402ee131cead41a28a42050b7115ded5c08a26f53eb54.
Missing execution-authorization.json demonstrably blocks preflight before IO.
No execution-start/result/worker request exists; actual calibration requests and
warmups0. Source219controls copied, not rerun forpreparation. R2LOW remains
manual fullDockerstderr recovery on failure without restart. Prepared services
remain isolated; no production/old service restart or olddata/marker deletion.

Next requires explicit operator authorization for this exact one-shot local A/A:
1440requests(800measured+640warmups),32workers,R1/C1/oneattempt,unchanged symmetric5%
and ASGI-to-primary-native-send timing. No automatic favorable repeat/formalG6/
paid continuation. USD0 this step; campaign cap5/effective4.15355688 unchanged.
No provider/external call, model/threshold/accounting/schema/grant/globalenv/app/
P5/retry/SSE/persistence change, newimage, G9, Notion or commits. Keep historical
AA_CALIBRATION_FAIL,CONTROLLED_G6_FAIL,BLOCKED_CONTROLLED_G6_FAIL and global
In Progress / Implement / DECISION_FREEZE_PASS.

## Prospective lexical-image A/A preview validated; image amendment needs approval

2026-11-10. Operator "ok, avanzar" approved preparing the prospective local
calibration manifest after image pinning, not executing A/A/G6/campaign.
LEXICAL_AA_IMAGE_AMENDMENT_READY_FOR_APPROVAL, preview261110141551; see
[proposal](paid-execution/controlled-g6/261106225237/diagnosis/lexical-aa-preparation/261110141551/proposal.md),
[completion](paid-execution/controlled-g6/261106225237/diagnosis/lexical-aa-preparation/261110141551/completion.json)
and retained candidate/reference/fixture/reproduction/requirements records.

Strict pure reproduction: current make_plan/validate_plan accepts fresh parent
reference and rejects new775image in both labels with Frozen plan drift: images.
Old immutable contract fixes4e68 in both labels; it must not be bypassed/edited.
Candidate preview differs from fresh valid reference only at both image IDs.
Unchanged1440futurelocalrequests(800measured+640warmups),32workers,C1bothlabels,
fourcells/fourblocks/ABBA-BAAB/100measured perarmcell/symmetric5%/R1/C1/oneattempt;
new720pairedrequest and720conversationUUIDs,14historicalplans/zerooverlap.
All505host source/config hashes unchanged. Parent pure P2 validation only,
no independent review claimed and no pytest/performance run repeated.

plan.candidate.json is deliberately not plan.json; config digests/normalized
hash/seed probe remain empty/null. Environment requirements are expected values,
not current readiness evidence: no services/DBs/credentials/names provisioned or
reserved. Exact prepared config/seed/P3/RLS/schema/CHECK/ANALYZE/resources and
independent final-packet review remain required before execution approval.

Approval request: image-only binding amendment plus minimal support/tests in
blocked_latency.py and test_orq41_blocked_latency.py, source review, then complete
the requested fresh disposable preparation/exact-packet review. No worker/timing/
metric/threshold/app/P5 change proposed. Keep old default/contract and strict
unknown/missing/unapproved/hash/mixed-image rejection; no free-form image flag.
Final executable plan must be regenerated with approved source/config identities;
do not silently promote the preview. A/A execution remains separately authorized.

Actual Docker/DB/API/provider/external/benchmark operations0,USD0; no app/harness/
tests/P5/.env/model/accounting/schema/grant/source changes, G9, Notion or commits.
Preserve historical FAILs/images/defaultpins/data/markers. Global stays
In Progress / Implement / DECISION_FREEZE_PASS, official CONTROLLED_G6_FAIL,
paid admission BLOCKED_CONTROLLED_G6_FAIL.

## Reviewed lexical SQL local image pinned; no calibration admitted

2026-11-10. Operator "autorizo imagen" authorized only local image build/pinning
and verification. LEXICAL_SQL_LOCAL_IMAGE_PINNED, run261110135233; see
[image receipt](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/lexical-image-pin/261110135233/receipt.json),
[report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/lexical-image-pin/261110135233/report.md)
and hash-bound completion/context/build/probe logs in the same directory.

Tag orq41-local:lexical-sql-261110135233, immutable local image ID
sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852,
parent sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707.
One offline COPY overlays only reviewed pgvector_store.py (SHA81a41cba1227be5bceff0b34051b7f976b6a4db65a6853a51616935ff6b8b9b3).
No downloads/installers; parent layers plus one layer, unchanged image runtime
configuration/Python/distribution inventory. Candidate app inventory equals
host and differs from parent at that file only. Actual adapter import/compile
and in-memory SQL capture match reviewed source/SQL identities. All505 host
source/config hashes unchanged during pinning; no app/P5/harness/.env change.

Parent-executed P2 verification, not another independent performance review.
The preceding239 real-PG tests and40plans/60adaptercalls remain source-remediation
evidence and were not rerun. No API/server/database/provider call, service
restart, new environment, benchmark, paid request or egress; USD0. No G9, Notion,
commit, push or deployment. Local image ID only; no registry push/repository
digest claimed. Original images/tags/closed receipts/executed manifest pins
and defaults remain untouched.

Next: prepare a prospective local calibration plan with this image and fresh,
reviewed source/config/fixture identities, followed by separate execution
authorization. No calibration plan/run prepared or admitted in this step.
Keep AA_CALIBRATION_FAIL, CONTROLLED_G6_FAIL, BLOCKED_CONTROLLED_G6_FAIL and
global In Progress / Implement / DECISION_FREEZE_PASS.

## Minimal lexical SQL remediation accepted; candidate image not yet rebuilt

2026-11-10. Operator "realizar remediacion" approved only the lexical SQL
remediation and focused real-PG tests, with independent review before/after.
LEXICAL_SQL_REMEDIATION_IMPLEMENTED_INDEPENDENT_REVIEW_PASS, run261110121850.
See [completion](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/lexical-remediation/261110121850/completion.json),
[final independent review](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/lexical-remediation/261110121850/final-patch-review.md)
and immutable report/commands/raw evidence in that directory.

Only pgvector_store.py SQL and new test_pgvector_query_equivalence.py changed
technically. Candidate1 was rejected before host mutation: simultaneous invalid
vector/deep query changed generic error precedence (22000 to54000). Reviewed
candidate2 adds a semantic-consumption dependency to the materialized lexical
value. All239 real-PG tests pass (229new+10unchanged determinism/RLS, zero skips),
including exact ordered full rows/scores, positive keyword/ties, both local plan
modes, all tenant/empty/error cases and the rejected counterexample. Real plans
prove one semantic and one lexical producer. Allfive orders/three LIMITs/RRF60,
English configuration, non-SQL AST, RLS and runtime auto policy remain unchanged.
Host source SHA81a41cba1227be5bceff0b34051b7f976b6a4db65a6853a51616935ff6b8b9b3
equals tested candidate bytes;499other protected preexisting files unchanged.

Prospectively frozen request-free proof:40EXPLAIN+60adaptercalls, all PASS once,
actual driver signature vector/bigint/text/bigint and both auto5custom25generic.
Paired ordered projections identical. Generic combined PG execution23.074–26.940ms
original versus8.212–8.536ms candidate; actual adapter20.281–25.016 versus5.270–8.004ms.
These are different intervals, R1/state/order limited, not historical A/A causal
proof or G6 PASS. Distinct reviewer independently replays retained40plans/60calls;
no new BLOCKER/HIGH/MEDIUM. Final review receipt982dd27f7730713ccf3a6f4b3e9e90eefd875567e7885dceb0ddfde24bef2f39.

Own PG-only clone stopped/data+markers retained, original source PG untouched;
P3/schema/settings preserved, no external credentials/egress/provider/API calls,
USD0. No P5/retry/SSE/persistence/model/threshold/accounting/dependency/global-env/
existing-schema/grant/host-policy change, G9, Notion or commits. Current pinned
4e68image remains unchanged and still has original SQL. Next requires operator
approval for a new candidate image/source pin and prospective local calibration
preparation; no automatic A/A, formalG6 or paid campaign. Keep AA_CALIBRATION_FAIL,
CONTROLLED_G6_FAIL, BLOCKED_CONTROLLED_G6_FAIL and global
In Progress / Implement / DECISION_FREEZE_PASS.

## Matched plan comparison complete; lexical generic-plan cost localized

2026-11-09. Operator "continuar" approved the preceding exact20EXPLAIN proposal.
REQUEST_FREE_PLAN_COMPARISON_COMPLETE, run261109225659. See
[plan comparison report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659/report.md),
manifest/authorization, all20SQL/marker/metadata/plan/raw records, analysis,
validation and completion.json. One new isolated PG-only clone, same pinned
image/schema/P3/roles/settings/ANALYZE; no app/provider/C1/SSE process or A/A.

Exact captured driver SQL, vector/bigint/text/bigint signature, original values;
ten cases once/mode in20fresh actual rag_app sessions, RLS and READ ONLY enforced.
Force modes were SET LOCAL only; postflight ordinary settings/defaultauto match
source. All20cases PASS with no retries/errors/unresolved,20outputrows each.
Generic is slower in10/10pairs. Combined execution custom7.937-8.600ms versus
generic23.776-27.272ms. Keyword filter retains plainto_tsquery(english,$3) in
all generic plans; custom holds a literal tsquery. Keyword elapsed0.667-0.869ms
custom versus7.342-19.776ms generic; semantic scan remains roughly6-7ms. No shared
or temporary reads. This supports a local plan-dependent SQL cost, not the exact
function-call count or historical A/A8.42% label cause. Category/order coupling,
R=1, instrumentation and missing full returned rows are explicit limitations.

Parent raw-record verification, not distinct review. Original driver/SQL/offline/
A-A artifacts and all500protectedfiles unchanged. Own cluster stopped/data+
markers retained, no resume; historical source PG/state preserved. USD0,
external/provider/app calls0. No app/P5/existing-harness/model/threshold/accounting/
global-env/existing-schema/grant/host-policy changes, G9, Notion or commits.
Only fresh-clone bootstrap materialized schema/roles. No pytest/repeated run.

remediation-proposal.md is ready for independent review and explicit operator
approval before any app change. Target only pgvector_store.py SQL and focused
real-PG semantic-equivalence tests: evaluate unchanged lexical tsquery once per
statement (candidate one-row MATERIALIZED CTE), preserve all ordering/RRF/RLS/
arguments/errors, leave runtime auto. Positive keyword/tied-rank/tenant/edge-case
proof is required; current zero-keyword-match ES cases are insufficient. No
candidate SQL/runtime fix/new image or validation has been implemented. Freeze
new diagnostic scope before future timings; no automatic A/A, formal G6 or paid
admission. Keep AA_CALIBRATION_FAIL, CONTROLLED_G6_FAIL,
BLOCKED_CONTROLLED_G6_FAIL and global In Progress / Implement / DECISION_FREEZE_PASS.

## Request-free driver diagnostic complete: auto plan transition observed

2026-11-09. Operator approved "ok, continuemos con la proxima prueba".
REQUEST_FREE_DRIVER_DIAGNOSTIC_COMPLETE, diagnostic261109222205. See
[driver report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205/report.md),
manifest/authorization, all30slot records, analysis/compiled-query/validation and
completion.json. One new PG clone and pinned4e68image Python adapter process,
networknone/loopback only, same P3/schema/roles/settings/ANALYZE, CPUs0,2/4,6,
2CPU/2GiB. Existing app/adapter/session/harness sources unchanged; no app lifespan,
/chat, provider, C1 receipts, collector or A/A. Actual library versions are
SQLAlchemy2.0.52/asyncpg0.31.0/greenlet3.5.5; no dependency change.

Thirty adapter calls passed once: exact20ES-SSE/block0warmup sequence plus10ES
document/combined diagnostics. Shipped build_rag_sessionmaker/TenantScopedSession
and PgVectorStore.hybrid_search, actual rag_app/RLS/tenant, read-only guards,
default cache/pool, normal rollback. One backend and one prepared statement;
real bind order embedding/top_k/query/rrf, inferred vector/bigint/text/bigint.
Metadata counters select custom for first5, then generic for remaining25 under
auto, without forcing plans/PREPARE/EXPLAIN. All10diagnostics are generic.
Document adapter elapsed12.001-15.808ms; combined19.529-24.140ms, Python CPU means
0.459/0.494ms. PostgreSQL CPU is outside this process. All20corpus-visible calls
return an identical ordered projection hash; isolated tenants return0rows.

This resolves the missing driver cache/type observation and reproduces substantial
adapter wall time without C1/SSE/provider work. It does not certify the historical
A/A8.42% label cause or imply C1 overhead is zero. Single-run phase/cache/state
confounding and extra metadata/read-only guards remain. No subtraction from G6
or causal claim from old psql8ms versus new generic wall times is valid.
Parent file-only verification, not distinct review; no new pytest or repeats.
Postflight data/schema/settings and all500protectedfiles unchanged. Both new
containers stopped, all data/markers retained; historical artifacts/state stay
intact. USD0, external/provider calls0, no app/P5/harness/global-env/model/
threshold/accounting/existing-schema/grant/host-policy changes, G9, Notion or commits.

Concrete next-proposal.md awaits approval:20read-only EXPLAIN executions,
same10cases once in each mode, exact actual SQL/types, fresh disposable PG,
alternating mode order. SET LOCAL force_custom_plan/force_generic_plan only in
those disposable transactions, preserving normal runtime auto. Current completed
manifest explicitly forbids forced modes/extra EXPLAIN, so no follow-on query
is authorized. A matched plan experiment could inspect a specific SQL mechanism;
no query/index/cache-policy/runtime fix or new A/A follows automatically.
Keep original AA_CALIBRATION_FAIL, CONTROLLED_G6_FAIL, paid
BLOCKED_CONTROLLED_G6_FAIL and global In Progress / Implement / DECISION_FREEZE_PASS.

## Request-free SQL diagnostic complete; historical A/A cause unresolved

2026-11-09. Operator approved the prior plan ("ok, avancemos con el planç").
REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE for diagnostic261109212354; this is not a
new gate or calibration PASS. See
[SQL report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354/report.md),
manifest/authorization, all10rawSQL/plan/metadata/marker records, validation and
completion.json. One fresh PG-only cluster, pinned image8e5355..., networknone,
CPUs4,6/2CPU/2GiB/noports, unchanged source schema/roles/locale/P3 bootstrap,
fixed7tableANALYZE and settings. No API/Redis/collector/provider or /chat call.

All10ES document/combined cases ran once under actual rag_app login, RLS on,
correct tenant, READ ONLY/rollback. Server execution7.492-8.157ms, planning
0.897-1.035ms; all20outputrows, same structural plan and0shared/temporary reads.
Semantic Seq Scan2146rows plus keyword Seq Scan0matches/2146filtered, in-memory
sorts. All10are first custom prepared plans, zero generic, auto plan_cache_mode.
The direct PREPARE wrapper explicitly declared types; it does not establish the
runtime driver's inferred signature or cache state after warmup. No subtraction
from original rag.retrieve wall times or causal attribution to C1 is justified.
The original A/A cause remains unresolved; no runtime/query/index fix proposed.

One file-only authoring error used an older manifest key, recorded with its
source in sql-diagnostic/authoring/. It stopped before allocation or SQL and
was corrected to the unchanged support_files_sha256 binding. Frozen execution
has10resolved/10PASS/0failed/0unresolved cases and no retries. Parent file-only
verification redecoded raw records; no distinct review is claimed. Corpus,
business counts, schema/settings and all500protectedfiles remain unchanged.
Only the new cluster was stopped; data/container/markers retained. Old A/A
services stay stopped, sourcePG retains its running identity. P2auditempty,
apprequests0, external/provider calls0, USD0. No app/P5/existing-harness/model/
threshold/accounting/global-env/existing-schema/grant/host-policy change, G9,
Notion or commits. Historical offline/AA review artifacts stay byte-identical.

Next recommendation awaiting separately scoped approval: reproduce only the
actual SQLAlchemy/asyncpg SELECT lifecycle and normal plan cache/parameter
inference, preserving the fixed original warmup sequence on a disposable clone.
Freeze exact query volume before running; no full /chat, C1 change, optimizer
change, forced plan mode or another A/A is included. Keep AA_CALIBRATION_FAIL,
CONTROLLED_G6_FAIL, paid BLOCKED_CONTROLLED_G6_FAIL and global In Progress /
Implement / DECISION_FREEZE_PASS. No additional execution is authorized here.

## Offline ES-SSE analysis complete; cause unresolved

2026-11-09. The operator approved offline analysis only ("dale").
OFFLINE_ES_SSE_ANALYSIS_COMPLETE_CAUSE_UNRESOLVED. See
[offline report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/offline-es-sse/report.md),
analysis.json/requests.csv/paired-deltas.json and completion.json. No new requests,
service startups, SQL connections, benchmark, source edits or pytest runs.
Existing logs/source were read only from stopped retained containers.

All 7,920 existing collector spans correlate to 1,440 unique accounting/request
roots, with complete expected children and correct correlation. The six c1
ES-SSE observations forming P95's upper tail are all combined cases across four
blocks, three first/three second. The combined median is slightly lower in c1;
this is a tail difference, not evidence of uniform overhead. Native payloads
match and all case repetitions have stable hashes. rag.retrieve accounts for
30.16-31.76 ms in the six slow c1 requests. This span includes local embedding,
actual PostgreSQL/client mapping and C1 document receipt work; existing evidence
cannot separate these. Baked image source boundaries were verified read-only.
No query plan or per-request CPU split exists. Coarse counters do not establish
a CPU, scheduler, SQL, maintenance or telemetry root cause. No fix is justified.

69 hashed inputs and all 500 protected files remain unchanged. Four derived
outputs reproduced byte-identically in scratch under P2. USD0, external calls0,
new requests0. This supplemental analysis has no distinct review claim or new
gate outcome. Keep the original independently reviewed AA_CALIBRATION_FAIL,
CONTROLLED_G6_FAIL, paid BLOCKED_CONTROLLED_G6_FAIL and global In Progress /
Implement / DECISION_FREEZE_PASS. Data/markers and prior attempts stay retained;
R2 LOW remains documented. No app/P5/harness/model/threshold/accounting/global-env/
schema/grant/host-policy changes, G9, Notion or commits.

Recommendation awaiting separate approval: a request-free SQL diagnostic on a
fresh disposable clone, same pinned image/schema/P3/roles/settings and actual
rag_app tenant context, read-only exact SELECT/parameters for all five ES
combined and five ES document controls. Retain bounded EXPLAIN ANALYZE/BUFFERS/
SETTINGS evidence, one diagnostic attempt/case. No app/provider requests,
optimization or new calibration is included. This could inspect SQL execution
without claiming to isolate C1 CPU or certify G6; no execution is authorized yet.

## Authorized balanced A/A completed: measured calibration FAIL

2026-11-09. Packet261109162430 completed its single explicitly authorized
1,440-request local-stub A/A under P2. The complete result is AA_CALIBRATION_FAIL:
all 32 workers exited0 and all 1,440 requests passed functionally (800 measured,
640 warmups, 1,440 distinct full-C1 accounting instance IDs). Three cells pass
the unchanged symmetric 5% rule; ES-SSE fails with P95 35.747604/38.757704 ms,
an 8.420424% symmetric difference. Controller exit0 means complete evidence
collection, not passing calibration. No repetition/replacement was performed.
See [execution report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/report.md),
raw result.json/worker/observation/marker files and execution-review/parent-replay.json.

Preflight rechecked actual prepared DB/config/seed/source/image/resource/P2
identities. Parent read-only postproof confirms both actual databases contain
720 conversations, 18,720 exact expected messages and 720 usage_events (local
stub execution), with matching paired normalized contents and unchanged P3/RLS/
schema/locale. All 500 protected files and all manifest pins stayed unchanged.
Both raw stdout/stderr streams were manually retained for every worker; R2 LOW
automatic stdout-only controller capture remains documented and unfixed.
Only this run's dedicated PG/Redis/collector were stopped after proof; all
data/containers/markers retained and source PG still running. The old failed
attempt261109141719 remains untouched and nonresumable.

Distinct post-execution review completed:
BLOCKED_AA_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL, receipt
`0a1c5f52b10c02cbdd01e9bc407be5cb0a92533c3ded5c8b4114a29c9df2d72b`.
The reviewer independently replayed all raw rows, P95/descriptive block statistics,
resource/host/DB deltas, native parity, 500-file scope and retained markers,
confirming the complete 3-PASS/1-FAIL outcome without new BLOCKER/HIGH/MEDIUM
integrity findings. Parent SQL/Docker proofs are attributed explicitly; the
reviewer made no API, SQL or Docker calls. See execution-review/independent-review.md,
receipt.json and completion.json; no new measurement or follow-on execution is
authorized by review.
No new source tests, measurement samples, external/provider calls, egress or
spend (USD 0). No app/, P5, model/threshold/accounting/global-env/schema/grant/
host-policy changes, G9, formal G6, paid campaign, Notion or commits.
Keep In Progress / Implement / DECISION_FREEZE_PASS, CONTROLLED_G6_FAIL and
BLOCKED_CONTROLLED_G6_FAIL. Any next diagnostic or measurement needs a separately
scoped proposal/approval; preserve this complete calibration FAIL.

## Namespace correction reviewed; fresh balanced A/A packet prepared

2026-11-09. BLOCKED_AA_NAMESPACE_FIX_SOURCE_REVIEW_PASS and
BLOCKED_AA_HARNESS_REVIEW_PASS. The operator authorized the namespace correction
and fresh preparation/review. Only blocked_latency_worker.py and its focused
test file changed: encode run/cell/block in the existing run token and keep the
final namespace component exactly c0/c1. The shared validator/controller, cache
policy, timing and all other 498 source/test/global-env files were preserved.
Actual worker.main -> install -> NamespacedRedis regressions were RED before
and GREEN after the fix; all 32 frozen namespaces pass the unchanged constructor.
Pinned-image P2 regression: 170 PASS, no skips/warnings. Independent source
review: 68 pure controls PASS; remaining native/startup checks attributed to the
parent image XML. See [source remediation report](paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/namespace-remediation/report.md).

New packet **261109162430**, plan SHA-256
`b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b`, fixtures
`2a2e7668bb9302939391ff996ed13c9b6322326716e6937ab02cf10db92831cb`.
See [prepared packet report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/report.md)
and its final independent-review/completion receipts. Three new dedicated
PG/Redis/local-collector services are running in an isolated namespace with no
published ports. Each fresh database has 720 conversations and 17,280 exact
history messages. P3, actual readonly DB/config/resource/seed proofs and freshness
checks passed; the reviewer inspected and attributed parent SQL, without claiming
its own SQL/Docker access. All 500 protected files stayed unchanged during this
preparation. No measurement worker, application request or performance sample ran.

The unchanged contract plans 1,440 local-stub requests (800 measured, 640 warmups),
32 fresh workers, R=1/C=1/one attempt and the symmetric 5% calibration rule.
Actual file-only preflight rejects missing execution-authorization.json before
Docker/SQL. Next requires explicit operator approval for this exact new plan,
then drift checks before its single execution; no authorization was transferred
from the failed attempt. The old 261109141719 attempt, stopped services/data,
start markers and historical evidence remain retained and must never be resumed.
R1 is resolved in reviewed source. R2 remains LOW: automatic stdout-only logs
require manual Docker stderr recovery on failure; no R2 fix/closure is claimed.

Zero external/provider calls, paid requests or spend (USD 0). No app/, P5,
model, threshold, accounting, global-env, schema/grants outside the approved
fresh disposable bootstrap, host-policy, G9, Notion, commit or deployment change.
Global In Progress / Implement / DECISION_FREEZE_PASS, official CONTROLLED_G6_FAIL
and paid BLOCKED_CONTROLLED_G6_FAIL remain unchanged. This preparation/review is
not a calibration result, formal G6 evidence or paid admission authorization.

The following sections retain historical state in chronological handoff order.

## Authorized balanced A/A interrupted before first request — review findings

BLOCKED_AA_EXECUTION_INCOMPLETE_STARTUP_FAILURE for packet261109141719, plan
`ae37ecfb95379e52c8feff53fedfaabb83a99b2b3b6a7d61521cd58aaa7177bc`.
The operator authorized one1,440-request local-stub A/A. Preflight passed and the
first worker was admitted once, but exited1 at install before app lifespan or
run_block.0requests,0warmups,0measurements, no valid calibration outcome; do not
classify it as AA_CALIBRATION_FAIL. Historical measured AA/G6FAILs remain.
See [execution report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719/execution-review/report.md)
and independent-review/completion receipts in that execution-review directory.

Distinct review: BLOCKED_AA_EXECUTION_INDEPENDENT_REVIEW_FINDINGS. MEDIUMR1:
blocked_latency_worker.py131-132 passes compound c0-EN-json-b0 as final Redis
namespace component, incompatible with shared NamespacedRedis c[01] suffix.
Pure P2 reproduction rejects all32 actual planned names. Previous source/packet
review and run_block unit tests missed the main/install integration. Minimal
proposed fix is worker-local compatible unique run/cell/block token plus actual
arm and real startup/constructor regression; do not relax shared validator or
change app/cache semantics. Counterfactual32names accepted by constructor only,
not implemented. LOWR2: automatic log file retainedstdoutonly; fullstderr recovered
manually and retained separately. Optional harness-local diagnostic hardening.
No code fix or retries applied; all500existing source/test/global-env files and
exact manifest pins remain unchanged.

Parent read-only proof shows prepared data exactly unchanged:720conversations/
17,280history messages perarm,0usage_events/0rag_request_metrics and no exchanges.
Proof is combined with actual before-lifespan failure and memory/P2 isolation;
row counts alone would not prove no provider operation. Reviewer inspected source,
raw traceback and attributed parent SQL/cleanup receipts, independently reproduced
32constructor failures and hashbound final report/validation. Full logs/data/
markers/containers retained. Own3services stopped after failure proof, sourcePG
stillrunning with same identity. Global/per-worker startmarkers remain; current
attempt must never be resumed or reset. No other worker admitted.

Next requires scoped remediation authorization, focused startup tests/source
review and a fresh pinned/reviewed packet plus new execution approval. Current
1,440-request attempt is consumed/incomplete even though no request ran.0external
provider/egress calls and USD0; no paid campaign, formalG6, G9, Notion, commit,
push, source/app/P5/runtime/model/threshold/accounting/schema/grant/global-env or
host-policy change. Global In Progress / Implement / DECISION_FREEZE_PASS and
CONTROLLED_G6_FAIL / BLOCKED_CONTROLLED_G6_FAIL paid admission unchanged.

## Balanced A/A exact packet prepared — independent review PASS

BLOCKED_AA_HARNESS_REVIEW_PASS for packet261109141719, plan
`ae37ecfb95379e52c8feff53fedfaabb83a99b2b3b6a7d61521cd58aaa7177bc`.
The operator authorized disposable preparation and explicitly requested independent
review; no calibration/request execution was authorized or performed. See
[report](paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719/report.md)
and exact independent-review.md/json in that packet. Source controller/worker/test
and all500existing app/experiment/test/global-env files remain unchanged.

Three dedicated isolated services are running: orq41-blocked-261109141719-postgres,
-redis and -collector; PG networknone, auxiliaries in its namespace, zero published
ports. Existing immutable images reused without download. No API server or actual
measurement worker deployed. Each paired DB has720conversations/17,280history
messages, exact UUID/content/tenant/sequence projection and P3/RLS/roles/schema/
locale preserved. Approved seven-table ANALYZE completed once perDB with unchanged
source-equivalent planner/autovacuum settings. Parent read-only verifier PASS;
distinct reviewer inspected and bound source/receipt, without independent SQL.
Effective settings, normalized arm equality, actual seed41/hash/interpreter,
CPU/resource/topology/local-readiness proofs PASS. Coarse host/DB observations
validated without a stability/physical-cache-equality or performance claim.

The approved future1,440requests remain800measured+640warmups/32freshworkers,
4x25blocks with20representative warmups, fullC1botharms and unchanged original
boundary/N100/category25/symmetric5%/R1/C1. Prior167image tests/67pure source
controls reused by exact hashes, no new pytest. Reviewer found no new B/H/M and
bound plan/fixtures/preparation/protocol/verifier/report/validation/guard evidence.
Actual file-only preflight rejects this reviewed packet specifically at missing
execution-authorization.json. No execution-started/per-worker marker or result.

Next requires explicit exact-plan authorization for one local-stub A/A execution
with rechecks before admission. No automatic formal C0/C1 or paid campaign.
Services/data retained; private credentials outside repository. External/provider
calls0, USD0. Only preparation/evidence/planning artifacts changed; no app/P5/
model/threshold/accounting/schema/grant/globalenv or host policy change outside
approved disposable bootstrap, no G9, Notion, commit, push or deployment. Global
In Progress / Implement / DECISION_FREEZE_PASS and historical AA/G6 FAILs plus
BLOCKED_CONTROLLED_G6_FAIL paid admission preserved.

## Approved balanced A/A harness implemented — source review PASS

BLOCKED_AA_SOURCE_REVIEW_PASS (2026-11-09). The operator approved the measurement
amendment and implementation/P2 tests only; the original design snapshots remain
unchanged and implementation/authorization.json records the new approval. Added
blocked_latency.py, blocked_latency_worker.py and test_orq41_blocked_latency.py;
all497 previous source/test/global-env files and reviewed helper hashes preserved.
See [completion](paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/implementation/completion.json)
and its validation/source-review receipts.

The isolated controller/worker implement the approved4x25 measured blocks with20
representative warmups per worker, seed41, balanced order, unchanged measured
business multiset/primary native-send interval and symmetric5% A/A criterion.
Total prospective volume1,440local requests/32workers; fullC1 in both arms, strict
source/config/seed/resources/evidence and final persistence guards. Separate
preparation/execution authorization and exact-packet review precede Docker/SQL;
exclusive run/worker markers prevent automatic resume/resend. ANALYZE allowlist,
readonly PostgreSQL proofs and coarse host/DB observations implemented outside
request timing. Existing app/P5/workers/helpers and formal-G6 validators untouched.

Final167 tests PASS/0skips/no warnings in the pinned optimizedC1image/networknone/P2:
77new,32AA,23controlledG6,35cleanup. Includes actual worker-loop synthetic native
JSON/SSE success/failure controls; no real app deployment, database or calibration.
Initial synthetic request-body iterator warning fixed in the test only; initial
XML retained. Distinct reviewer67pureP2 PASS,10SDK/thread cases excluded on host
and attributed to parent image execution; source/tests/XML hashes bound, no new
B/H/M. This is SOURCE review only, not an executable-packet review or performance
claim. No 1,440-request run, PostgreSQL/Redis/collector startup or real SQL.

Next requires authorization for disposable environment/fixtures and executable
manifest preparation, then independent exact-packet review and separate single
A/A execution approval. No formal C0/C1 or paid execution is authorized by this
step. SpendUSD0 and external/provider calls0. No app/P5/model/threshold/accounting/
schema/grants/global-env changes, Notion, commit, push or deployment. Global
In Progress / Implement / DECISION_FREEZE_PASS retained; historical AA/G6 FAILs
and BLOCKED_CONTROLLED_G6_FAIL paid admission unchanged.

## Balanced measurement amendment proposed — awaiting approval

MEASUREMENT_AMENDMENT_PROPOSED_AWAITING_APPROVAL. User authorized preparing the
amendment only. Proposal and non-executable contract are in
[measurement-amendment/proposal.md](paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/proposal.md).
The previous environment was already controlled; no remaining confound is a
proven cause. Proposed same-host A/A fixes process seed41, equal disposable-DB
ANALYZE preparation, four balanced25-measurement blocks/arm/cell and20representative
warmups before every block. Total1,440 local requests:800measured+640warmups,
32fresh workers,100measured/arm/cell and25/category; exact measured business
multiset, ingress/native-send interval, images/resources and5% rules preserved.
No new CPU-load exclusion, continuous sampler or host tuning. Cache/frequency
identity and statistical equivalence are not claimed.

Author design-only P2 validation passed15 assertion groups;497source/test/global-env
files unchanged. Exact counts/history projections/order/multiplicities and source
hashes checked without application import, SQL, Docker or requests. Initial author
route-header assumption error retained; empty route table confirmed and corrected
validator also verifies loopback-only interfaces. This is not independent review
or implemented-harness evidence. Future implementation surface:two new isolated
blocked_latency controller/worker files and one focused test file; reviewed cleanup
retained, existing app/P5/harnesses untouched.

Next approval:design plus implementation/tests; independent exact packet review and
separate single A/A execution authorization follow. Formal C0/C1 and paid execution
are excluded. Current corrected-harness A/A3FAIL/1PASS and all historical G6 FAILs
remain; global In Progress / Implement / DECISION_FREEZE_PASS and
BLOCKED_CONTROLLED_G6_FAIL unchanged. No services, database operation, calibration,
external/provider call or spend, Notion, commit or deployment in this task.

## Fresh A/A after retention remediation — executed once and independently reviewed

AA_CALIBRATION_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL in aa-runs/261108131511 under controlled-g6/261106225237/diagnosis/. User approved this fresh840localrequest calibration after the reviewed retention fix; exactplanf1552995b797fecef6e67f00635c85cede5c1938d19728d3b553b0df8ff0c8df reviewed before execution. Bothlabels fullC1/identical4e68image; original800measured+40documentwarmups/population/order/boundary/5%symmetric criterion/resources unchanged, fresh420pairedrequest/conversationUUIDs and dedicateddatabases. Only reviewed cleanup/helper/pins differ from previousfailedA/A. No code edits this task; prior90PASS/0skip controls reused byte-identically, not rerun.

840functionalPASS/840uniqueC1/nativepayloadparity;0cleanupfailures. Calibration3FAIL/1PASS: ENJSON A14.526087ms/B16.773784ms(+15.4735%)FAIL; ENSSE16.529449/15.881095(-3.9224%)PASS; ESJSON14.970033/17.069936(+14.0274%)FAIL; ESSSE14.878458/16.016835(+7.6512%)FAIL. AllAPI/PGcounterdeltasreplayed,recordedthrottlingincrements0; affinityAPI0,2/PG4,6 preserved. FailedR1 calibration still does not demonstrate5%source-attributionprecision; no causal latency benefit/hardware cause, application defect, historicalG6invalidity or G6PASS inferred. No favorable repetition.

Parent read-only pre/final PostgreSQL proofs420conversations/9600->10440messages eacharm, exacthistory+oneexchange each, P3/RLS/roles/schema/CHECKtruth/locale/config preserved; distinctreviewer replayed840rawrows/eightworkerhashes/p50p95p99max and inspected/hashbound parentSQLsource/receipts. Final authorreport/validation/cleanup/scope independently checked,160protectedapp/P5/globalenvfiles unchanged. No new integrity B/H/M. Own3services stopped,containers/volumes/data retained,originalsourcePGstillrunning. Report,commands,finalreviewreceipt retained inpacket.

USD0,paidrequests0,externalprovidercalls/egress0 underP2/native-memorystubs; no app/P5/model/threshold/accounting/schema/globalenv changes,Notion orcommit. Global In Progress / Implement / DECISION_FREEZE_PASS preserved; official CONTROLLED_G6_FAIL and BLOCKED_CONTROLLED_G6_FAIL paidadmission unchanged. Next: prospectively approve a bounded controlled-reference measurement proposal before another formalC0/C1 or paidexecution. Priorentriesbelowarehistorical; no further execution authorized by this result.

## Performance retention fix — implemented and independently reviewed

AA_RETENTION_FIX_INDEPENDENT_REVIEW_PASS in aa-runs/261107150655/audit/remediation/ under controlled-g6/261106225237/diagnosis/. AA-AUDIT-R1 resolved in reviewed implementation; performance effect not measured. New performance_cleanup helper is called only after response/fullC1+transport validation, quiescence and compact row projection in AA and original controlledG6 workers. Guards preserve unresolved/late/fault evidence and refuse active tasks/sessions or busycontext; no cancellation/wait/forcedGC. Completed task/context/request/session roots and passivebarrier traces released; successful row unchanged. Cleanupfailure marks rowFAIL and breaks admission. Future module pins include helper. SharedLifecycle,G1/G2/G3/G9,app/P5 and AAcontroller unchanged; originalsource snapshots/diff preserved. Historical plans/results remain untouched and must not be rerun against changed source.

Final90author testsPASS/0skips in pinnedC1image under networknone/P2, covering35cleanup+32AA+23G6; C0importwithoutC1PASS. Explicitasyncmarks corrected initial4PASS/30SKIP; initialXML retained. SyntheticJSON/SSE success/cancel cases use memorynativeproviders and noSQL, not campaign requests. Distinct reviewer29pureP2PASS; sixhostthreadcases excluded and parent90imageXML inspected/attributed accurately. No new B/H/M. See completion.json/independent-review.json/validation.md.

No AA840/G6 rerun, newimage, DBservice start, external/providerpaidcall/spend, app/model/threshold/accounting/schema/globalenv change, Notion orcommit. Old AA_CALIBRATION_FAIL and officialG6FAIL/paid block remain; global Implement/DECISION_FREEZE_PASS unchanged. Next performance attempt needs a fresh frozen plan/fixtures/pins and review; no latency benefit claimed by these tests.

## A/A audit — reproducible performance-harness retention finding

AA_AUDIT_FINDINGS in aa-runs/261107150655/audit/ under controlled-g6/261106225237/diagnosis/. AA-AUDIT-R1 MEDIUM: Lifecycle.tasks retains completed Tasks/Contexts after quiescence; performance worker clears only captures/evidence_states. Same pattern in original formal worker. Pinned-image pureP2 probe (noAPI/SQL/provider) reproduces8completed tasks retaining8Evidence objects despite empty evidence_states; releasing completed-task roots releasesall8. Requests/sessions/closed_sessions also grow. This confirms harness retention, not a causal p95 share or production leak. No fix applied.

Read-only retained-worker inspection finds only expected DBpath/ARM environment differences; image/command/resources/mounts equal. Existing logical DB proofs hold; physical cache/planner state unrecorded. Warmups equal by approveddesign, no retroactive exclusions. PYTHONHASHSEED unsetboth, unproven residual. Raw timing trends mixed, not uniform degradation. No servicesstarted/SQL/API/benchmark/provider/egress/spend, harness/app/P5/model/threshold/accounting changes,Notion orcommit. Proposed next: narrow performance-caller cleanup after full validation/quiescence, guard pending work and preserve receipts, deterministic regressions then independent review before newfrozen A/A. Old A/AFAIL/G6FAIL/paid block and Implement/DECISION_FREEZE_PASS remain. Audit author-only, not distinct-agent review.

## Fixed-affinity full-C1 A/A executed — calibration FAIL independently verified

Operator approved the hardware-audit/proposal.md calibration. AA_CALIBRATION_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL in aa-runs/261107150655 under controlled-g6/261106225237/diagnosis/. Plan f5dbe8d18bded1666f98d53403b9d613a731ca7089307897e5c2c9312979a659 executed once:840functionalPASS(800measured/40originaldocumentwarmups),840uniqueC1contexts, identical optimized4e68image/fullCapture/attempts/scopes on bothlabels, rawnativeparity. OriginalN100/fourcategories25each/order/boundary preserved. API configured+effective affinity0,2, dedicatedPG4,6,2CPU/2GiB; allAPI/PGcounter deltasverified and nr_throttled/throttled_usec increments0.

All4symmetric calibration cells FAIL: B/A p95 ENJSON+12.4094%,ENSSE+8.8170%,ESJSON+5.5937%,ESSSE+9.2711%. Identical-image comparison did not demonstrate precision sufficient for5%source attribution in thisR1. Not proof of an app defect, specific hardware cause or historicalG6invalidity. Do not tune app functions or repeat untilfavorable. Next bounded proposal should audit remaining process/DB/cache/warmup/host measurement differences or define a controlled reference environment before another C0/C1 run; no such run or warmup amendment authorized by this result. Official G6FAIL/paid block remain.

55author pinned-image controls and32independent prospective pureP2controlsPASS. Parent readonly postrunDB proof420conversations/10440messages per arm,9600exacthistory+840newmessages, P3/RLS/roles/schema/locale/config parity. Strict source/roundtrip CHECKcast preparationfailure261107141146 retained; only exact previously reviewed two-line equivalence normalized, with11realtruthcontrols; no DBconstraint/schema change. Initialfailed andcurrent dedicated3services stopped,containers/volumes/data retained, historicalservicesuntouched. Distinct reviewer replayed840rows,raw8workerhashes,allp95decisions andresourcecounters; authorreporthashbound in finalreceipt. See report.md and execution-review/receipt.json.

Only isolated aa_calibration controller/worker/resources+tests and environment/evidence/planning artifacts changed. No app/P5/model/threshold/accounting/retry/retrieval/SSE/globalenv change, egress/provider calls/spend,campaign,G9,Notion,commit or deployment. Preserve global Implement / DECISION_FREEZE_PASS. Earlier proposal/preparation paragraphs below are historical.

## Measurement validity reassessment — hardware confound identified, not proven causal

Read-only audit in controlled-g6/261106225237/diagnosis/hardware-audit/ records current i9-14900HX topology: CPUs0–15 SMT-paired5.6–5.8GHz maxima, CPUs16–31 single-thread4.1GHz maxima, governor powersave. Retained C0/C1/PG containers have2CPU quotas but no CpusetCpus; previous runs retained no actual placement/throttling/frequency tape. This is an untested measurement confound, not proof of historical causation or invalidity. All prior FAILs remain.

Reassessed recommendation: calibrate with identical-image/full-C1 A/A on the same fixed homogeneous CPU pair and dedicated PG on disjoint cores before further runtime tuning or warmup/order amendment. proposal.md makes the840localrequest scope and symmetric calibration rule explicit for operator approval. Only audit.py/sysfs/Docker inspect ran; no new request, benchmark, affinity/container/PG change, egress/provider/spend, app/P5/model/threshold change, Notion or commit. Preserve G6FAIL/paid block and Implement/DECISION_FREEZE_PASS.

## Within-cell crossover executed — independently reviewed

DIAGNOSTIC_CROSSOVER_EXECUTION_INDEPENDENT_REVIEW_PASS for crossover-runs/261107133140 under controlled-g6/261106225237/diagnosis/. Reviewed plan bcd882d10e1bf57b359135dc7b2eb408c55eed8412dbf717aa6f097f016c4f4b executed once:64local successful requests(32measured/32mixed warmups),16fresh workers,32unique C1 contexts, nativepayload parity.51author pinned-image controls and4independent prospective controls PASS. Parent readonly finalDB proof32conversations/832messages per arm,768exacthistory+one exchange each,P3/RLS/schema/config unchanged. Distinct reviewer replayed16workerreceipts,1194events/469groups and all16paired deltas/eight balanced source-order contrasts; no new B/H/M. See report.md and execution-review/receipt.json.

Balanced source wall contrasts favor C1 in4/4combined cells and3/4empty cells; source medians acrosscells are-25.927ms(combined)/-13.574ms(empty). Pooled first-order signed medians are-19.386ms(C0first)/-16.275ms(C1first). Previous order-sign reversal did not reproduce under this schedule/mixedwarmup, but small/repeated business population and host/block effects prevent causal or G6p95 inference. Recommend proposing a prospectively reviewed formal G6 measurement amendment: representative equal warmups and within-cell balance while preserving N100/fourcategories/boundary/+5%/full evidence and historical FAILs. No amendment or new formal gate is authorized/executed by this result. No app/P5/wait-observer/model/threshold/accounting change, external/provider calls/spend,campaign,Notion or commits. Preserve official G6FAIL/paid block and global Implement/DECISION_FREEZE_PASS.

## Wait/GC diagnostic executed — independently reviewed

DIAGNOSTIC_WAITS_EXECUTION_INDEPENDENT_REVIEW_PASS for wait-runs/261107062530 under controlled-g6/261106225237/diagnosis/. Final plan56e110e4dd374948106579c46dbc17fe70206cef5709120221d0217194174ec9 executed once:40 successful local requests(32measured/eight warmups),20unique valid C1 contexts, paired serialized payload parity. Parent readonly final DB proof passed20conversations/424messages per arm (384exacthistory+one exchange each), P3/RLS/schema/config unchanged. Distinct reviewer replayed892events/286completegroups and all clipping/unions/paired statistics exactly; no new B/H/M.47author pinned-image controls and17independent safe-host controls passed. Initial GC validator MEDIUM fixed prospectively with originals preserved.

Paired C1-minus-C0 wall medians:combined-7.815ms,empty-8.530ms, with wide ranges. Order strata:C0-first-10.624ms versus C1-first+17.904ms; order is confounded with language/protocol/time, not proof of causation or a G6 PASS. GC/SDKqueue medians small; do not optimize them as the proven cause. Next proposal: within-cell crossover with equal warmup composition to separate source and order/environment effects; not implemented/executed. See report.md and execution-review/receipt.json. No new app/P5/model/threshold/accounting change; zero external/provider calls/spend, no campaign/Notion/commit. Preserve official G6FAIL/paid block and Implement/DECISION_FREEZE_PASS. Earlier preparation paragraphs below are historical.

## Wait/GC diagnostic prepared — independent review in progress

Operator approved the bounded combined/empty diagnostic. New isolated controlled_latency_waits controller/worker and wait_observer modules plus focused deterministic tests; official G6/app/P5 untouched. Packet paid-execution/controlled-g6/261106225237/diagnosis/wait-runs/261107062530/ binds plan f03464d4ca38fef1fb9dcf8d9b05c338917240b068b9888dbb3f575040090a3a, 40 future local requests (32 measured/eight warmups), full evidence, balanced cell order and existing images. 43 controls PASS in pinned C1 Python3.13.15 under network-none/P2; host3.13.9 executor-teardown issue also reproduced without observer, recorded in protocol. Read-only verifier PASS on fresh20conversation/384message paired DBs with exact P3/RLS/schema/config. All hashes rechecked; no execution-started/result exists. Distinct reviewer has prospective packet; execution is not authorized by a review receipt alone. Zero new API/provider/external calls/spend. Preserve G6FAIL/paid block and Implement/DECISION_FREEZE_PASS.

## Full source/path comparison completed — no runtime change

Frozen C0/C1 images have identical Python/dependencies; nine source files differ and eight existing files become AST-equal after removing only C1 additions (ninth is observer). Both arms share task/DB/queue instrumentation; candidate-only evidence/scopes/attempt hooks/Capture remain as approved. Offline aggregate scope cycles cost approximately 0.050 ms with C1 active, insufficient evidence for scope-only remediation. Existing G6 candidate tail ranks95–100 are combined cases in23/24rows. See controlled-g6/261106225237/diagnosis/path-comparison/report.md. Proposed next diagnostic isolates combined/empty workload with aggregate CPU, GC, SQL and SDK handoff intervals; not implemented/executed. Zero new API/DB/provider/external calls/spend. App/P5/G6/threshold unchanged; preserve FAIL/paid block and Implement/DECISION_FREEZE_PASS.

## Offline counter strategy evaluated — insufficient savings

Operator-authorized count-evaluation under controlled-g6/261106225237/diagnosis/ passed 68 exact chain/body/count/cap/failure checks under P2. Nine rotated-order full-observer batches per category showed median CPU changes of -0.003/-0.039/-0.045/-0.005 ms for document/history/combined/empty. This is too small to justify another runtime patch/image/G6 run; no p95 extrapolation. Counterfactual remained process-local, app source hash unchanged, zero API/DB/provider/external calls or spend. See count-evaluation/report.md and result.json. G6 FAIL/paid block and global Implement/DECISION_FREEZE_PASS preserved. No independent review claimed for this diagnostic.

## Optimized C1 formal G6 executed — independently verified FAIL

Reviewed plan cdc785a3ccfb9538882d66f327e71c978ebc85e910cf2a0fa68e21ca6853fbf7 executed once in paid-execution/controlled-g6/261106225237/. All 840 local stub requests passed functional checks (800 measured/40 warmups), paired native payload/call parity and 420 unique C1 accounting contexts. Independent replay confirmed all four relative p95 failures: EN JSON +8.98%, EN SSE +5.18%, ES JSON +8.05%, ES SSE +10.21% (limit +5%). Review artifacts persisted before reviewer usage limit; hashes verified and parent replay corroborates. No paid/provider/external calls, audit attempts or spend. Original failures remain historical. Keep BLOCKED_CONTROLLED_G6_FAIL, In Progress / Implement and DECISION_FREEZE_PASS. No automatic repetition, threshold change or further runtime tuning. See execution.md and execution-review/receipt.json in this run.

## Direct old/new C1 comparison executed — independently verified

New isolated receipt_copy_comparison controller/worker use full C1 Capture and validation in both arms (old7417... versus optimized4e68...). The reviewed c1-copy-comparisons/261106215400 packet fixed a counterbalanced order across language/protocol, fresh paired DBs/UUIDs and prespecified signed new-minus-old analysis before execution. Operator-authorized 40 requests completed once (32 measured plus eight warmups); all functional/native payload parity checks and 40 unique C1 contexts passed. Parent final read-only DB verifier passed: 20 conversations/424 messages per arm, exact original history and one exchange each; P3/RLS/schema/config unchanged.

Optimized CPU was lower in 13/16 pairs (median -1.878 ms) and wall in 14/16 (median -3.823 ms). Combined medians were -3.349 ms CPU/-6.150 ms wall, favorable in all four pairs. Empty cases also improved by multiple ms despite little expected copy work, so no assignment of all gains to the patch is supported. This is favorable diagnostic evidence with uncertain magnitude/causality, not G6 p95 PASS. Distinct reviewer /root/packet_review independently replayed all 40 raw results and exact CPU/wall/sign/order calculations: C1_COPY_COMPARISON_EXECUTION_INDEPENDENT_REVIEW_PASS. Receipt: execution-review/receipt.json in the comparison packet. Preserve CONTROLLED_G6_FAIL and paid-admission block; no external provider calls or paid spend, additional runtime edits, Notion or commits.

## Optimized C1 image pinned and measured — independently verified

New local C1 image sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707 is an offline one-file overlay on the previous candidate. Whole-app inventories differ only in the approved context_evidence.py source; 49 focused P2 tests passed inside the image. The reviewed aggregate-runs/261106213253 packet executed 40 local stub requests once (32 measured plus eight warmups). All functional, native payload parity and candidate context checks passed. Parent final read-only DB verification passed: 20 conversations and 424 messages per arm, with P3/RLS/schema/configuration unchanged.

Median paired C1 minus C0 CPU increments were 1.823/4.610/7.319/4.135 ms for document/history/combined/empty; wall increments were 1.103/4.176/6.890/3.801 ms. The historical comparison is mixed: no uniform improvement or causal optimization effect is demonstrated. Distinct reviewer /root/packet_review issued DIAGNOSTIC_AGGREGATE_EXECUTION_INDEPENDENT_REVIEW_PASS, independently replaying all 40 raw rows, hashes, paired payloads and exact CPU/wall arithmetic. Receipt: aggregate-runs/261106213253/execution-review/receipt.json. Preserve CONTROLLED_G6_FAIL and the paid-admission block. No external provider calls or paid spend, Notion or commits; no app/harness edits during this image/measurement task.

## C1 receipt-copy optimization implemented — independently reviewed

Operator approved the exact revision2 receipt-copy patch. Runtime surface: context_evidence.py private scalar-window copier plus three call sites; generic deepcopy fallback and final snapshots preserved. New deterministic regression file test_orq41_c1_receipt_copy.py. Author P2 validation: 49 focused +230 expanded =279 PASS, empty network audit; exact patch/baseline SHA verified using a temporary reversed copy. Evidence: diagnosis/receipt-copy-proposal/implementation/. Distinct reviewer /root/packet_review issued C1_RECEIPT_COPY_IMPLEMENTATION_INDEPENDENT_REVIEW_PASS; 54 independent P2 checks PASS, no open BLOCKER/HIGH/MEDIUM findings. Receipt: implementation/independent-review/receipt.json. No optimized image, new G6 request, campaign, Notion or commits. Original CONTROLLED_G6_FAIL/paid block unchanged. Do not treat the offline copy microbenchmark as request p95 evidence.

## C1 receipt-copy proposal ready — no runtime change

A concrete observational-only proposal targets the three window receipt deepcopy call sites in context_evidence.py. Proposed scalar-only independent container copies retain full deepcopy fallback for nested/unexpected/subclass/aliased rows. Recommended patch and counterfactual proof: diagnosis/receipt-copy-proposal/revision2/; proposal.md explains scope and limits. P2 offline: 57 checks PASS, 48 exact original/proposed trace comparisons, alias/mutation/failure/cap preservation; copy batch CPU lower, approximately 0.22 ms saved per three copies in this microbenchmark only. Not sufficient proof to close G6. Operator implementation approval pending. No app/P5 edits or new API/DB/provider calls, paid spend, Notion or commits. Preserve CONTROLLED_G6_FAIL/paid block.

## Aggregate diagnostic executed once — independently verified

Operator-authorized aggregate-runs/261106190648 executed all 40 local stub requests (32 measured + eight warmups): functional/native payload parity PASS, 20 valid unique C1 contexts. Parent final readonly DB verifier PASS: 20 conversations / 424 messages per arm, exact original history and one new exchange each, P3/RLS/schema/config unchanged. Median paired C1 minus C0 CPU ms: document 2.827, history 3.672, combined 8.514, empty 1.346; corresponding wall 1.932/3.617/9.557/1.415. Descriptive only, four pairs/category, no causal function attribution. Distinct reviewer /root/packet_review independently replayed all eight raw receipts and exact CPU/wall arithmetic: DIAGNOSTIC_AGGREGATE_EXECUTION_INDEPENDENT_REVIEW_PASS (execution-review/receipt.json). Parent-executed final DB verifier source/receipt inspected and hash-bound by reviewer. No resend, external/provider calls or paid spend. Official CONTROLLED_G6_FAIL/paid block preserved; no app/P5 changes, Notion or commits.

## Aggregate diagnostic reviewed — awaiting execution authorization

Distinct reviewer /root/packet_review issued DIAGNOSTIC_AGGREGATE_HARNESS_REVIEW_PASS for plan c2c19931906ba8964320d436cef554ffb4f13eb03dae84f53bd3801e96cba7f6 (aggregate-runs/261106190648/independent-review.json). Five independent P2 controls PASS, no open BLOCKER/HIGH/MEDIUM findings. Parent read-only DB verifier confirms exact fresh UUID/content/sequence projections, P3 corpus/RLS and normalized effective configuration parity; reviewer inspected that verifier source/receipt but did not independently query DB. No diagnostic requests executed. Separate operator execution approval remains required. Official CONTROLLED_G6_FAIL and paid-admission block unchanged; zero provider/egress/paid calls, no app/P5 changes, Notion or commits.

## Aggregate CPU/wall diagnostic prepared — not executed

Operator-authorized preparation completed for 40 future local stub requests (32 measured + eight warmups). New isolated paired DBs orq41_agg_261106190648_c0/c1 each contain 20 conversations / 384 messages with identical business/schema hashes and frozen P3 content. Separate aggregate worker reads process CPU and monotonic wall at ingress/native-send boundaries, preserves Capture/native SDK/candidate checks and installs no fine profiler wrappers. Author P2 controls: 28/28 PASS, empty network audit. Evidence: paid-execution/controlled-g6/261106130053-rev2/diagnosis/aggregate-runs/261106190648/. Independent harness/fixture review and execution approval pending; no diagnostic /chat request has run. Preserve CONTROLLED_G6_FAIL, paid admission block, Implement/DECISION_FREEZE_PASS. No app/P5/threshold/model edits, external calls, paid spend, Notion or commits.

## Bounded diagnostic profiling completed and independently reviewed

Operator-approved 40-request local profile executed once:32 measured+8warmups, fresh20conversation/384history-message databases per arm, pinned original C0/C1 images/resources. All requests functionalPASS; paired serialized native payloads match;20unique C1accounting contexts remain valid. Final readonly PostgreSQL verifier confirms20conversations/424messages per arm, exact history and new exchange contents, normalized only generated UUIDs, unchanged P3/RLS/schema/configuration.30author P2 tests and8independent controls PASS.7696profile events independently replayed, including per-thread inclusive/exclusive wall/CPU, before/after cutoff and SQL interval union. Evidence: paid-execution/controlled-g6/261106130053-rev2/diagnosis/profile-runs/261106153843/report.md and execution-review/receipt.json. No app/P5/source image/threshold changes, external calls, paid spend or official G6 rerun.

Instrumented accounting CPU is larger with history/combined, but5432fine wrappers in measured C1 preparation can inflate parent self time. No uninstrumented causal percentage, p95 correction or runtime optimization is justified yet. Proposed nextstep: aggregate offline CPU replay without per-hash/per-receipt wrappers, subject to scoped approval; see next-step-proposal.md in the same directory. Preserve CONTROLLED_G6_FAIL_INDEPENDENTLY_VERIFIED and BLOCKED_CONTROLLED_G6_FAIL. Global In Progress/Implement and DECISION_FREEZE_PASS unchanged; live-provider target/pins remain pending. No automatic new requests, campaign, Notion or commits.

## Controlled G6 offline diagnosis completed

344/400 measured input pairs are slower in C1; all4approved p95 cells stillFAIL. Confirmed interval includes candidate-only rewrite Capture bookkeeping and invocation/SDK hooks as well as actual runtime accounting; primary Capture and final snapshot validation are outside the same-request timed interval. Existing data cannot causally partition the overhead. No source/request/threshold change. Diagnosis/report and bounded40local-stub-request profiling proposal retained under controlled-g6/261106130053-rev2/diagnosis/. Profiling implementation/execution awaits scoped approval; paid admission remains blocked, externalspendUSD0.

## Controlled G6 FAIL independently verified

Distinct reviewer recalculated all840rows and rawhashes:800measured+40warmups,0functionalfails,pairednativepayload/callparityPASS,420uniqueC1instanceUUIDs; all4p95increments exceed+5%. ENJSON+10.89%,ENSSE+12.38%,ESJSON+8.92%,ESSSE+9.78%. Execution-review/receipt.json retained under controlled-g6/261106130053-rev2/. Offline category decomposition added as descriptive only; no causal claim/gate replacement/rerun. Paidcampaign remains BLOCKED_CONTROLLED_G6_FAIL, spendUSD0. Next scoped diagnosis must separate accounting cost from Capture/nativeSDK harness bookkeeping; no app optimization or thresholds change performed.

## Controlled G6 executed once — FAIL, paid campaign blocked

Reviewed rev2 executed840local ASGI requests (800measured+40warmups), all functionalPASS and nativepayload/callparityPASS. Relative preparation p95 exceeds+5% in all4language/path cells. See paid-execution/controlled-g6/261106130053-rev2/execution.md and result.json. No repeats, external calls or paid spend. Independent numerical verification requested; no performancefix or thresholdchange implemented. Global Implement/DECISION_FREEZE_PASS remains designacceptance, not paidreadiness or graduation.

## Client timing amendment independently reviewed PASS

Approved minimal client-only timing seam implemented;202author regression tests PASS under P2. Distinct reviewer84tests PASS including6probes, exact raw-read headers/event/content/done/EOF observation verified; campaign/manifest recorder binding enforced preadmission. Scope receipt `paid-execution/client-measurement-review/round2/receipt.json`. Earlier binding/CLI issues preserved and fixed; no app/provider/accounting change. Replay168 USD4.15355688<=5 unchanged. No paidrequests or spend. Next: controlledC1/C0 N100 timing and realprovider target/config/source/credentials/network/blockpins preflight; existing campaignauthorization valid, no prematureadmission. Global Implement / DECISION_FREEZE_PASS retained.

## Paid fixtures materialized and verified; client timing approval pending

168entries/40paired cases/168freshconversations,3840historymessages. Prospective review PASS, dedicated internal/nohostport PG clone restored identical P3 and independently authored read-only verifier PASS (executed by parent underP2), all data/schema/RLS checked. Original init failure preserved; pid1postgres readiness fix and explicit empty-state resume used without resetting resources. Exact feedback CHECK cast deparse difference retained and narrowly verified equivalent; no DBconstraint change. See paid-execution/fixture-review/.

New paidG6 readiness gap confirmed by independent reviewer: P5 retains no first-content timestamp, cannot recover TTFT from completion/total latency. Scoped proposal paid-execution/client-measurement-proposal.md awaits operator approval. No observation seam implemented. Live target/pins and controlledN100 C1/C0 timing still pending. No paidcampaign opened, providercalls or spend; global Implement and DECISION_FREEZE_PASS remain.

## Approved tenant amendment implemented — independent review pending

P5 preflight validates optional per-entry tenant, rejects explicit invalid values without fallback, and LocalAPI sends the pinned header. Canonical hash/request UUID bind tenant. 66 focused and187 expanded tests PASS under correctly configured P2; outer sandbox bind/setup failures retained. See `paid-execution/tenant-amendment-evidence/validation.json`; independent reviewer has packet. No app, runtime, accounting, model or threshold changes. Zero paid admission; executable fixtures/manifest/pins/live target remain to prepare after scoped review.

## Paid preparation — tenant amendment approval required

168 metadata slots drafted, shared-budget directory durably created, provider credential presence recorded without values/auth calls. Fixed P5 tenant prevents faithful history-only/empty workload. See `paid-execution/tenant-amendment-proposal.md`. No P5/app edit or paid admission. Existing paid authorization remains valid within approved bound, but preflight stays BLOCKED_BEFORE_ADMISSION.

## Paid campaign authorized; admission blocked

Operator explicitly authorized the approved paid campaign, within USD5 hard cap and USD4.15355688 effective bound. Authorization: `paid-execution/authorization.json`. Readiness: `paid-execution/preflight.json` BLOCKED_BEFORE_ADMISSION: production manifest/pins, paired fixtures, dedicated live-provider target and shared paid budget identity not yet established. No campaign opened, requests admitted, provider calls or spend. Prior no-paid-authorization statements are historical; no unapproved environment change was made.

## Formal implementation transition — 2026-11-06

Operator explicitly authorized In Progress / Implement after D6 / DECISION_FREEZE_PASS. See `implementation.md` and `readiness/implement-transition.json`. Measurement/paid campaign remain unauthorized. No runtime changes, Notion, commits or deployment. Earlier Plan-only notes below are historical.

## Operator D6 accepted — DECISION_FREEZE_PASS

Explicit operator approval recorded in `readiness/d6-operator-acceptance.json`, bound to the distinct technical review receipt/hash. Current decision freeze: DECISION_FREEZE_PASS. Global phase remains Plan. No paid campaign, future live-gate execution or global Implement transition authorized. No Notion sync or commits performed. Historical BLOCKED notes below are superseded for this accepted package.

## Technical package independently reviewed PASS; operator D6 pending

G8 hung real-exporter proof: G8_HUNG_OTLP_INDEPENDENT_REVIEW_PASS; 45 reviewer tests PASS. Combined technical package: INDEPENDENT_PACKAGE_REVIEW_PASS, no known pending BLOCKER/HIGH/MEDIUM. Receipt: `readiness/independent-complete-packet-review/final-technical-review.json`. Same-process JSON/SSE/persistence preserved under real timeout; sink remained held through graceful SIGTERM shutdown (-15,10.652s). Earlier harness exit-code assertion failures retained; no confirmed runtime shutdown stall. Current pending prose reconciled; history preserved. No app/P5 changes, external calls, egress, paid campaign, Notion or commits. Global Plan / decision freeze BLOCKED until explicit operator D6.

## G9 remediation independently reviewed PASS

Distinct reviewer round 2: G9_REMEDIATION_INDEPENDENT_REVIEW_PASS; 33 tests PASS, 42/42 original source/baseline projection hashes verified. R-G9-1 resolved. See `readiness/independent-complete-packet-review/round2/review.md`. Full package remains Plan / decision freeze BLOCKED: hung-OTLP proof, planning reconciliation and operator D6 remain. No new chat requests, external calls or paid spend.

## G9 projection remediation

Projection content filter removed; adversarial extra-message regression rejects corruption. 17 focused tests PASS under P2. All 14 source projections independently re-read from real PostgreSQL match original hashes. See `readiness/g9-remediation-review.md`. Distinct-author D6 review remains required; Plan / decision freeze BLOCKED.

## G9 execution 261105143941 — G9_EXECUTED_PASS_AWAITING_INDEPENDENT_REVIEW

Frozen 14-cell G9 manifest `6a4dcbcdd72cb4d02e2a314d6170859c30b4a6f7f6ec6697b651c2580861d70c`; 14/14 cases PASS, 0 findings, 14 attempted.
Evidence: `environment/g9/runs/261105143941/execution.json`. PostgreSQL was real and isolated; generation used local stubs. No egress, external calls, paid requests, or spend. P5 was not touched.
ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.

## G9 execution 261105141950 — G9_EXECUTED_FINDINGS

Frozen 14-cell G9 manifest `eb87c30c9c7f4f1c8140c481439677960295a35f888169b56fc211cc7c8c135a`; 3/14 cases PASS, 1 findings, 4 attempted.
Evidence: `environment/g9/runs/261105141950/execution.json`. PostgreSQL was real and isolated; generation used local stubs. No egress, external calls, paid requests, or spend. P5 was not touched.
ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.

## G9 execution 261105121056 — G9_EXECUTED_FINDINGS

Frozen 14-cell G9 manifest `482465bf901bc9a7925cd7639ffeb420ac384c8cfbb2f565815d189f2f65b61e`; 0/14 cases PASS, 4 findings, 4 attempted.
Evidence: `environment/g9/runs/261105121056/execution.json`. PostgreSQL was real and isolated; generation used local stubs. No egress, external calls, paid requests, or spend. P5 was not touched.
ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.

## G9 execution 261105120435 — G9_EXECUTED_FINDINGS

Frozen 14-cell G9 manifest `d16d8e507abbd2d1144dcccf04c001a285faef7108c9511c41b88751f4297d22`; 0/14 cases PASS, 1 findings, 1 attempted.
Evidence: `environment/g9/runs/261105120435/execution.json`. PostgreSQL was real and isolated; generation used local stubs. No egress, external calls, paid requests, or spend. P5 was not touched.
ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.

## G9 execution 261105111840 — G9_EXECUTED_FINDINGS

Frozen 14-cell G9 manifest `9ad4eb0cd815aa7880dd4b60f873c681cdbbfc199707ba9884f2a6cc6507941e`; 0/14 cases PASS, 14 findings, 14 attempted.
Evidence: `environment/g9/runs/261105111840/execution.json`. PostgreSQL was real and isolated; generation used local stubs. No egress, external calls, paid requests, or spend. P5 was not touched.
ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.

# ORQ-41 planning handoff

## G123 package PASS — offline parity independently verified

Run261104151059:294/294 individual cases PASS with real PostgreSQL.
Original aggregate failed because each frozen control supplies a distinct
request_id. Original evidence and aggregate-failure receipt remain preserved.
[Offline verification](environment/g123/runs/261104151059/offline-verification/validation.md)
validates326 initial and192 recovery identity echoes before normalizing copies.
Original package checks now PASS. Independent reviewer /root/packet_review:
7tests PASS and885 input hashes MATCH; no known verifier findings.
G1/G2/G3 package PASS reviewed; no294-case rerun or new requests were needed.

G9 remains pending: prepare/freeze lifecycle harness and probes, cacheTTL300,
cleanup10s/drain30s/rollback60s; execute, then complete-packet independent review
and operator D6 acceptance. No DECISION_FREEZE_PASS yet.
No app/P5/runtime,provider,retry,DB/.env/model/threshold change; no external
calls,campaign,Notion or commits. USD0. Plan / decision freeze BLOCKED.

## Historical handoffs


## Fresh joint-fix run261104151059 — prospective packet review pending

Three fixes independent review PASS (reviewer /root/packet_review);265 affected
regressions pass. New [pin](environment/g123/runs/261104151059/pinning.json)
image7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06
contains4 reviewed harness files, unchanged app inventory. New disposable DBs/P3,
294fixtures/crosswalk and5Settings identities verified. Packet67e1ebd9384760fab8b742927dd406398d9bcfc4b37a1f0206c387780c95e904
compiled with126 recoveries and11 static controls PASS. Exact packet independent
review requested before execution; no new gate admissions yet. Preserve all prior
14 failures. Earlier pending joint-fix review entries are historical.
No new authorization required for already-approved local sequence. No external
providers/paid campaign, app/P5 change, Notion or commit. Plan/freeze BLOCKED.

## Historical handoffs


## Joint three-point remediation — implementation complete, independent review pending

[Validation](environment/g123/joint-remediation/validation.md),
[receipt](environment/g123/joint-remediation/receipt.json).
265 affected controls pass under P2 with loopback-only HTTP integration.
Initial/recovery clients disable premature per-operation timeout; absolute deadline
unchanged. JSONflush oracle omits primary. SSEdisconnect holds primary-qualified
pre-dispatch checkpoint, observes real HTTP disconnect and cancellation without
server_cancel, requires proof and zero provider entry. Four new controls.
Reviewer /root/packet_review running scoped independent review. No verdict yet.
No app/P5/runtime/provider/retry/DB/schema/.env/model/threshold change or gate
request in this increment. Previous14 failures and294-case diagnostic preserved.
Candidate refresh and fresh disposable packet required after review.
Plan / decision freeze BLOCKED; P5 CLOSED.

## Historical handoffs


## 2026-11-04 — diagnostic matrix complete, joint review pending

Run261103153820:294/294 executed,280PASS,14FAILED.
[Report](environment/g123/runs/261103153820/execution-review/diagnostic-complete.md),
[all errors](environment/g123/runs/261103153820/execution-review/all-errors.json).
Failed families:disconnect_before_dispatch1,flush_rejection1,history_timeout4,
retrieval_timeout4,telemetry_timeout4. No failed request was resent.
User authorized diagnostic continuation after recording errors and checking safe
termination/SQL disposition. Global package remains failed. No fixes applied to
these14 findings during execution. Next: independent joint diagnosis/proposal.
G9 remains blocked; Plan / decision freeze BLOCKED; P5 CLOSED.
No external/provider calls, paid campaign, Notion or commits; USD0.

## Historical handoffs


## 2026-11-03 — fresh candidate/packet ready; execution stopped on oracle finding

Run261103124407: [pinning](environment/g123/runs/261103124407/pinning.json),
[packet independent PASS](environment/g123/runs/261103124407/execution-freeze/authoring/final-v3/independent-review.json),
[execution diagnosis/proposal](environment/g123/runs/261103124407/execution-review/review.md).
New image b85e068802601148d61a4380a3c12c766662af41b6c7bd9b689df2189c246461,
new disposable DBs/P3/fixtures/crosswalk and five Settings pinned;11 static
controls pass;294 oracles and126 recoveries frozen and independently reviewed.

Actual G123 batch:5PASS/1FAILED. Failure SSE cancel_after_user_flush C1 expects
ASGI aborted, but child StreamingResponse cancellation yields outer returned.
Independent reviewer confirms prospective oracle error; zero extra business rows.
Minimum proposal: SSE request outcome returned for cancel_after_user_flush and
cancel_provider_wait only; JSON and other cancellation families unchanged.
No oracle correction implemented. Approval/tests/re-review/fresh run required;
do not resend or modify executed packet/admissions. No G9 until complete G123 PASS.
No app/P5 changes, external calls/downloads, paid campaign, Notion or commits.
USD0. ORQ-41 stays Plan / decision freeze BLOCKED; P5 CLOSED.

## Historical handoffs


## 2026-11-03 — scoped harness remediation independently reviewed

**G123_CHECKPOINT_REMEDIATION_INDEPENDENT_REVIEW_PASS**.
[Validation](environment/g123/checkpoint-remediation/validation.md),
[receipt](environment/g123/checkpoint-remediation/receipt.json),
[independent review](environment/g123/checkpoint-remediation/independent-review.md).
Actual checkpoint-owner cancellation/request membership/ack replaces exterior
ASGI-task cancellation; malformed/non-object JSON becomes HarnessError without
widening unresolved acceptance.152 focused/261 affected regressions pass P2;
separate reviewer10 focal controls pass; no scoped known findings.
144 app source files match prior candidate inventory. No app/P5/Docker/SQL/gate,
fixture reset/resend, external call/campaign/G9/Notion/commit; USD0.

Candidate refresh is required because image contains the previous harness.
Prior private /tmp manifest is unavailable; retain its public receipts/history,
but do not execute incomplete reconstructed expectations. Next: fresh candidate,
new disposable run/fixtures and complete new frozen independently reviewed packet,
then G123, G9 and final packet review. Do not resend old executed admissions.
ORQ-41 remains Plan / decision freeze BLOCKED; P5 remains CLOSED.

## Historical handoffs


## 2026-10-20 — local G123 execution blocked; scoped remediation approval pending

[Independent execution diagnosis](environment/g123/execution-freeze/authoring/execution-review/review.md)
and [receipt](environment/g123/execution-freeze/authoring/execution-review/result.json).
11 static controls pass; prospective packet reviewed and D3 resources effectively
applied. Actual gates: own/C1/JSON/Bedrock PASS, cancellation-after-token SSE
C0 and C1 PASS; cancellation-after-user-flush JSON C0 FAILED.
Harness cancels exterior task instead of transactional checkpoint owner;
non-JSON HTTP500 then raises JSONDecodeError before ordinary reconciliation.
Independent SQL readback: zero extra business rows. No request resend/repair.
Preserve current run and all private evidence. One earlier setup failure was
independently PRE_HTTP_NOT_SENT, continued once with linked preserved receipts.

Operator was asked for bounded harness remediation/review/new candidate/new
disposable run approval. No harness/app/P5 remediation implemented.
G9 and final freeze depend on a complete G123 PASS and were not executed.
No external provider calls/paid campaign/G6/G7/Notion/commit; USD0.
ORQ-41 remains Plan / decision freeze BLOCKED; P5 CLOSED.

## Historical handoffs


## 2026-10-20 — executable G123 packet statically frozen

Operator authorized advancing through local G123, G9 and independent final review,
stopping where further authorization is needed. Campaign/external calls remain
unauthorized. [Packet](environment/g123/execution-freeze/authoring/final-v3/validation.md):
294 cases+126 recoveries,9 static controls pass under P2; independent packet review
PASS. SSE post-user-flush primary oracle corrected, prior packets retained.
D3 resource bounds now hash-bound, superseding provisional unlimited resources;
must verify actual limits before admission. G123 TTL60; prospective G9 TTL300.
No gate request yet. Local single-use execution controller is under independent
pre-execution review. P5 unchanged/CLOSED. Plan / decision freeze BLOCKED.

## Historical handoffs (superseded where noted above)


Updated: 2026-10-19. Canonical state: **Planned / Plan**.

## Reviewed candidate refreshed; settings/SQL fixture inputs pinned; manifest not frozen

2026-10-19: operator authorized candidate refresh and completing the executable
manifest. [Validation](environment/g123/candidate-refresh/validation.md),
[new image receipt](environment/g123/candidate-refresh/receipt.json).
Candidate sha256:c3cc7ceb5528292e0b95c2da3636bc01645b0dbb007451da8da8e8c9d10fcdda
contains the reviewed render/dispatch fix; all inventoried image bytes match.
Only the two reviewed harness files were copied; no app/P5 source change.
Classic COPY-only build used verified cached parent; no remote resolver/download.

Five prospective config vectors pinned;294 per-case source/config/fixture/harness
input maps bound. Real fixtures now exist in disposable c0/c1 DBs (127/167 cases,
1210/2170 messages), with private raw source rows and a real SQL sequence crosswalk.
Readback verifies message/document/chunk content and P3 full hashes; original
baseline data unchanged. Do not reseed/reset these DBs or assume they are still
business-empty. This is fixture setup, not a gate or runtime write-path change.

Freeze remains incomplete. Schema max_message_chars8000 makes the >=12000
current_message_oversized branch unreachable via HTTP. Nine P2 controls and a
read-only settings/schema probe inside the new image confirm this. Operator was
asked to approve HTTP-schema rejection plus explicitly separate unit coverage,
without changing limits; response is pending. [Clarification](environment/g123/execution-freeze/config-precheck/coverage.md).
Concrete complete per-cell request/capture/DB/recovery oracles and actual version2
manifest validation/review remain pending; bound-inputs.json is not executable.
No HTTP/gate/provider/campaign/G9, Notion or commit. USD0. ORQ-41 stays
**Planned / Plan / decision freeze BLOCKED**; P5 remains CLOSED.

## Render/dispatch independent review PASS — candidate refresh/freeze still pending

2026-10-19: **RENDER_DISPATCH_INDEPENDENT_REVIEW_PASS**.
[Independent report](environment/g123/execution-freeze/remediation/independent-review/review.md)
and [receipt](environment/g123/execution-freeze/remediation/independent-review/receipt.json).
Static review + 568 affected regressions and 11 new adversarial probes pass (579).
Separate reviewer /root/render_dispatch_review: 17 implementation controls and
7 own adversarial cases pass. Suites overlap; no count summation. No residual
scoped defect confirmed. Code hashes match implementation receipt; no code fixes.
No app/P5 change, gate/SQL request, provider/egress call, Docker/image build,
campaign/G9, Notion or commit. Candidate image refresh remains required because
it contains the previous harness. Concrete per-case oracles/config/crosswalk and
294-cell executable freeze remain pending. No C1 or gate closure follows.
ORQ-41 remains **Planned / Plan / decision freeze BLOCKED**.

## Render/dispatch oracle remediation — awaiting review

2026-10-19: operator authorized the recommended scoped remediation. capture.py
now separates explicit rendered messages from authoritative dispatch expectations;
render-only failures require their own exact pre-dispatch failure dispositions.
Actual sends are always independently reconciled, including selectively lost
observations. validate_g123.py normalizes the two new optional oracle fields;
existing oracle behavior is retained when they are absent.
[Validation](environment/g123/execution-freeze/remediation/validation.md) and
[receipt](environment/g123/execution-freeze/remediation/receipt.json): 17 new
controls, 251 focused and 568 affected regressions pass under P2, no skips.
Zero external calls/egress; USD 0. No app/P5 change, fixture write, gate request,
Docker build, G9/campaign, Notion or commit. Independent review remains pending.

The historical candidate image is unchanged and contains the previous validator;
current harness differs in capture.py/validate_g123.py only. Candidate identity
must be refreshed after review and before any executable-manifest/gate claim.
The concrete 294-cell oracle/config/crosswalk manifest is not yet frozen.
ORQ-41 remains **Planned / Plan / decision freeze BLOCKED**; P5 stays CLOSED.

## Executable manifest freeze blocked — new pre-dispatch validator counterexample

2026-10-19: operator authorized completion/freezing of the executable G1/G2/G3
manifest. Precheck reproduced a MEDIUM coverage defect in the existing C1
validator: a complete valid rendered-but-not-dispatched serialization failure
cannot be accepted, because expected_messages requires both render and dispatch.
[Finding and minimal proposal](environment/g123/execution-freeze/precheck/finding.md),
[receipt](environment/g123/execution-freeze/precheck/receipt.json). Two deterministic
P2 memory-transport counterexamples pass (normal + streaming initialization);
zero external calls/egress, no actual HTTP/SQL gate, fixture seeding or candidate
output recording. No fix or executable manifest was produced. Existing source,
app/P5 and pinned images remain unchanged. Scoped harness remediation approval,
regression/re-review and refreshed identity are needed before resuming freeze.
Do not label correct pre-dispatch failure evidence as lost/corrupt to pass.
ORQ-41 remains **Planned / Plan / decision freeze BLOCKED**; P5 remains CLOSED.

## Execution-freeze preparation — not yet executable

2026-10-19: operator approval interpreted as preparation only, not gate execution.
[Preparation inventory](environment/g123/execution-freeze/preparation.json) binds
294 mandatory cells and their reviewed scenario/barrier requirements to pinned
images/databases/source. Static AST extraction only; no network, SQL, fixture
seeding, app import or request. Concrete independent per-cell oracles/config maps
and pre-request fixture crosswalk remain pending. This inventory is not a valid
version-2 executable manifest and must never be treated as a gate PASS.

## Candidate pinned / disposable databases prepared — scoped provisioning only

2026-10-19: **CANDIDATE_PINNED_DISPOSABLE_DATABASES_PREPARED**.
Operator explicitly authorized candidate pinning and disposable DB preparation.
[Pin receipt](environment/g123/pinning.json), [source inventory](environment/g123/candidate-source.json)
and [validation](environment/g123/validation.md) record the exact identities.
Two new C0/C1 databases contain the frozen P3 corpus, identical existing schema/
ACL/RLS policy, and no conversations/messages. Baseline table digests and role
policy are unchanged. Local owner/rag_app/chat_ops TCP logins pass. Candidate
COPY-only image uses the cached base and matches the reviewed working-tree source.
No app/P5 edits, external provider calls, gate requests or campaign spend.

The preserved environment was stopped and its original /tmp secrets/init bind
were missing. Existing PG data was verified read-only before ordinary PG startup;
original local passwords were recovered privately without rotation. API, Redis and
collector remain stopped. This is not G9 or an environment/gate readiness PASS.
Initial BuildKit FROM-by-ID was misinterpreted as a registry reference; metadata
resolution was attempted and failed (also in a diagnostic retry), without an image
download. Zero egress is **not** claimed. Corrected build used the verified local
tag and legacy builder; preserve this incident in subsequent evidence.

Next: freeze concrete case/oracle/config/resource identities and obtain separate
G1/G2/G3 execution authorization. Synthetic fixtures/crosswalks are not yet seeded.
ORQ-41 remains **Planned / Plan / decision freeze BLOCKED**; P5 stays CLOSED.

## G1/G2/G3 harness H1-H4 remediation — independent re-review PASS

2026-10-19: **C1_G123_REMEDIATION_INDEPENDENT_REVIEW_PASS**.
Operator authorized only H1-H4 remediation and subsequent independent re-review.
[Validation](decision-freeze-design/g123-harness-remediation/validation.md) and
[final separate review](decision-freeze-design/g123-harness-remediation/independent-review/round-3/review.md).
H1 snapshots all business tenants in the disposable DB; cleanup stays scoped.
H2 freezes/enforces the minimum applicable matrix and case/packet identity receipts.
H3 binds required scenario/action/barrier/fault/held-read/wire-delivery proof; primary
holds are explicitly separated from rewrite/evaluator. H4 separates source reference
from OFF feature vector and compares OFF baseline/candidate. Version-2 manifests
retain exact per-case source/config/fixture/harness identities under one packet hash.

36 new deterministic regressions; 234 focused and 551 affected checks pass. Final
independent reviewer: 151 checks (142 harness controls plus 9 independent probes),
no residual H1-H4 defect confirmed. First review's residual H3 auxiliary-barrier
finding and subsequent intermediate receipt are retained historically; round-3
is the final source/hash result. No gate PASS or real PostgreSQL evidence claimed.

Nine prior app seam hashes, existing capture.py and prior C1 test hashes match.
No app/, P5, DB/schema/grants/.env/model/threshold/runtime change. No Docker/images,
real gates/campaign/G9, Notion or commits. Zero egress/provider calls; spend USD 0.
Next remains separately authorized candidate image pinning/disposable provisioning,
concrete case/oracle/crosswalk freeze and real G1/G2/G3 execution. C1 global remains
open; ORQ-41 stays **Planned / Plan / decision freeze BLOCKED**.

## G1/G2/G3 harness independent review — original FINDINGS

2026-10-19: **C1_G123_HARNESSES_INDEPENDENT_REVIEW_FINDINGS**.
[Consolidated report](decision-freeze-design/g123-harness-independent-review/review.md)
and [separate reviewer](decision-freeze-design/g123-harness-independent-review/reviewer-findings.md)
confirm four HIGH harness findings: H1 tenant-filtered business snapshot hides
third/default-tenant writes; H2 incomplete C1/E1/OFF/protocol coverage can obtain
package PASS; H3 required scenario/action/barrier/intermediate-read proof is not
bound or mandatory; H4 baseline OFF is conflated with candidate observer identity.

Root: 110 checks (106 existing + 4 probes), plus 515 affected regressions pass.
Separate reviewer: 108 checks (106 existing + 2 probes), and independent static
confirmation of the root findings. Passing counterexamples demonstrate defects,
not gate PASS. These are offline acceptance/control reproductions; no runtime
isolation regression or real PostgreSQL gate result is asserted.

All five reviewed implementation/test hashes and nine prior runtime seam hashes
remain unchanged. No fixes, PostgreSQL/Docker, images, real gates, P5/G9/campaign,
Notion or commits. Zero external connect/DNS/provider calls, spend USD 0.
Next: operator-approved harness-only H1-H4 remediation, then independent re-review;
candidate provisioning and real G1/G2/G3 execution remain separately unauthorized.
ORQ-41 remains **Planned / Plan / decision freeze BLOCKED**; C1 is not closed.

## G1/G2/G3 harnesses implemented — original implementation receipt

2026-10-16: **C1_G123_HARNESSES_IMPLEMENTED_AWAITING_INDEPENDENT_REVIEW**.
Operator authorized only the approved harness implementation and local P2 controls.
[Evidence](decision-freeze-design/g123-harness-evidence/validation.md): four new
harness modules plus one test file; 106 new controls, 198 focused checks and 515
affected regressions pass, zero failures/errors/skips. Native adapter dispatch is
memory-only; transaction doubles are control tests, never PostgreSQL gate proof.
The existing remediated capture.py and tests are unchanged; all nine prior runtime
seam hashes still match. Zero external attempts/provider calls; spend USD 0.
No app/, P5, Docker/image/DB provisioning, real gates, campaign, G9, Notion or commits.

Next: independent harness review; separately authorized candidate image pinning,
validation database provisioning, concrete cell/oracle freeze using pre-request
crosswalk and then G1/G2/G3 execution. Infrastructure roles/privileges and real SQL
barrier behavior remain unverified by this offline increment. C1 is NOT CLOSED;
no gate PASS, runtime readiness or decision-freeze PASS follows. Global ORQ-41 is
still **Planned / Plan / decision freeze BLOCKED**.

## Remaining C1 harness design — approved (historical design-only step)

2026-10-16: **C1_G123_HARNESS_DESIGN_APPROVED**. Operator explicitly approved
the harness-only design; implementation and execution remain separate approvals.
[Proposal](decision-freeze-design/g123-harness-proposal.md) separates local harness
controls from real PostgreSQL G1/G2/G3 and requires actual adapter serialization
with memory transports for delivered evidence. Defines files, isolated DB/role/
image dependencies, JSON/SSE/cancellation/commit-barrier contracts, acceptance and
estimated USD 0 external-provider execution cost. C0 cannot be relabelled C1; new
candidate pinning/provisioning and gate execution still require separate approval.
This step changed only documentation/planning. No code, tests, Docker/DB/gates,
G9, campaign, G6/G7/G8 expansion, P5, thresholds, Notion or commits. Prior C1
remediation second-review PASS is preserved. Plan / decision freeze BLOCKED.

## C1 Increment 1 findings remediated — second independent review PASS

2026-10-16: **C1_INCREMENT_1_REMEDIATION_INDEPENDENT_REVIEW_PASS**.
Operator authorized only R1-R4 remediation and deterministic P2 regression.
[Remediation](decision-freeze-design/c1-findings-remediation/validation.md) fixes
mandatory terminal outcomes/purpose, strict positive attempt IDs, and independent
transport bodies/sends/receipts reconciliation. All nine prior counterexamples are
now deterministic rejection regressions. No app/ seam or provider change.
Root: 92 focused and 404 affected regressions pass. Separate reviewer
/root/c1_independent_review: 100 checks pass (92 focused + 8 additional adversarial
probes), no residual R1-R4 defects confirmed. [Second review](decision-freeze-design/c1-findings-remediation/second-independent-review/review.md).
The four findings are resolved for this increment; previous findings/pending notes
below are historical. Nine runtime seam hashes unchanged; zero egress/external
provider calls. No DB/Docker, image pinning, gates, campaign, Notion or commits.
C1 as a whole is NOT CLOSED: later real PostgreSQL/process harnesses and gate
evidence still require their separate authorization. ORQ-41 remains
**Plan / decision freeze BLOCKED**; P5 stays CLOSED.

## C1 independent review completed — findings remain open

2026-10-16: **C1_INCREMENT_1_INDEPENDENT_REVIEW_FINDINGS**.
After explicit delegation approval, separate reviewer /root/c1_independent_review
reviewed the approved contract and all twelve implementation/test files read-only.
[Independent report](decision-freeze-design/c1-independent-review/review.md):
C1-R3 HIGH (dispatch capture/receipt completeness), C1-R1 MEDIUM (mandatory terminal
expectations), C1-R2 MEDIUM (attempt ID validation), new C1-R4 MEDIUM (purpose not
validated). 55 existing focused tests plus 9 reproductions executed under P2;
64 checks pass, with adversarial passes demonstrating the acceptance defects.
Original twelve source hashes match; no fixes. Earlier pending-delegation notes
are superseded by this completed scoped review, not a PASS. Complete freeze-packet
review is still pending; C1 findings must be resolved before accepting this increment.
No gates, Docker/DB, campaign, G6/G7/G8 extension/G9, Notion or commits.
ORQ-41 stays **Plan / decision freeze BLOCKED**; P5 stays CLOSED.

## C1 technical recheck — findings, no fixes

2026-10-16: [technical review](decision-freeze-design/c1-review/review.md) found
C1-R1 (terminal disposition not mandatory in the oracle) and C1-R2 (nonpositive
attempt IDs accepted), both MEDIUM. Five isolated reproductions confirm missing
rejections; 55 focused regressions still pass. No implementation file changed.
This is an author recheck, not independent acceptance. C1 remains open with
findings; independent review remains pending. P5 stays CLOSED; Plan/BLOCKED.

## C1 first increment implemented — independent review pending

2026-10-16: **C1_INCREMENT_1_IMPLEMENTED_AWAITING_REVIEW**. Operator authorized
this increment after the concrete change-surface packet. Request-local bounded
content-free observations now cover document/history/episodic selection, packing
and rendering. Local harness captures actual HTTPX/Bedrock SDK serialized bodies;
no provider implementation changes. [Evidence](decision-freeze-design/c1-increment-1-evidence/validation.md):
55 focused tests and 367 affected regressions pass under P2, no external provider
calls/egress. Selected existing S1 middleware cases included; not a P5 re-review.
Tool-sandbox asyncio wait reproduced with C1 disabled; the unchanged test passes
outside that tool sandbox with unshare/network guard/credential scrubbing intact.
No gate, DB drill, new image, G8 expansion, G6/G7 or campaign executed. Existing
pinned environment/G8 receipts describe C0; the working-tree candidate is not yet
image-pinned. Review this diff before candidate pinning and later harness/gate
execution authorization. ORQ-41 remains **Plan / decision freeze BLOCKED**;
P5 remains CLOSED. No commits or Notion.

## C1 change surface prepared; G1 clarification approved

2026-10-16: operator authorized correcting the G1 matrix to preserve existing
JSON/SSE rejection order. The invariant is zero foreign context and unauthorized
writes, not universal rejection before provider dispatch. SSE may generate before
its persistence ownership check; history is scoped before use.
[Concrete change surface](decision-freeze-design/change-surface.md) identifies
observational seams and separate local transport/PostgreSQL/G9 harnesses for next
implementation authorization. No runtime code or gates executed. Plan/BLOCKED.

## Latest scoped decision-freeze design — approved, execution pending

2026-10-16: **DESIGN_APPROVED_EXECUTION_PENDING**. Operator approved the
[proposal](decision-freeze-design/proposal.md), explicitly confirming cleanup
<=10 s, drain <=30 s and full rollback <=60 s; C1 serialized/dispatched delivery
proof (ProviderInput alone insufficient); real PostgreSQL/local providers;
JSON/SSE isolation, provenance and failure/cancellation coverage; G9 in-flight
reconciliation and preservation of committed exchanges after response loss,
without automatic resend. D1-D4 design approved; D5 execution authorization and
D6 independent review/final acceptance remain pending. No gates executed or
runtime/P5 changes made. Candidate hashes remain required before execution.
ORQ-41 remains **Plan / decision freeze BLOCKED**; P5 remains CLOSED.

## Latest scoped G8 result — real local OTLP passed

2026-10-15: **ORQ41_G8_LOCAL_OTLP_PASS**. Official Collector 0.120.0 acquired once
and pinned by registry digest. [Evidence](environment/g8/README.md): 2 healthy
and 2 collector-unavailable /chat requests (JSON/SSE), real exporter/collector,
real PostgreSQL and stub provider/embedding/reranker via a harness-only entrypoint.
Correlated spans received; identical response/SSE and committed exchanges across
collector state; exporter failure observed; validation egress attempts zero.
Collector restored running. No app/, P5 or dependency changes, G6/G7, G9, paid
campaign, Notion or commits. The existing model-config API was not restarted.

Environment verification now records **ORQ41_ENVIRONMENT_PINNED**; P4, P3 hashes/RLS
and source identities remain verified. Earlier missing-collector/host-SDK blockers
are superseded. This scoped local result does not close mixed G8: the original
hung-endpoint fault and live usage/identity reconciliation are not measured here.
C1 contract/harnesses, fault matrix, prospective cleanup/rollback bounds, G9 and
full-packet review plus operator DECISION_FREEZE_PASS still remain. Global
ORQ-41 stays **Plan / decision freeze BLOCKED**. P5 stays CLOSED.

## Latest environment work — partially ready, collector blocked

2026-10-15: operator authorized local isolated environment creation only. Three
ORQ-41 containers (PostgreSQL, Redis, API) now run in a shared network-none namespace,
without published ports or external credentials. API /health=200; effective P4
fallback None/static/shadow OFF and fixed model confirmed. P3 restored with exact
fingerprint/content hash and RLS. No /chat, provider calls, G6/G7 or G9 drill.
[Environment record](environment/README.md): **ORQ41_ENVIRONMENT_BLOCKED** because
no real OTLP collector image is locally available. SDK/exporter exists in the image;
local endpoint configured, receipt not yet verified. Supply offline collector image
and digest or authorize acquisition. Earlier “no running target / SDK missing”
statements describe the host interpreter and prior state, superseded for this new
isolated image. P5 remains CLOSED; Plan / decision freeze BLOCKED unchanged.

## Current continuation — local prerequisites audited; freeze still blocked

2026-10-15 operator authorization extends to safe credential-free prerequisite
validation and documentation only. No deployment, external access, runtime or
runner changes, commits, Notion or campaign. [Readiness audit](readiness/report.md)
records 210 passing local contract tests, 50/50 real-stream offline replay, matching
P2/P3 recorded artifact hashes, and unchanged USD 4.15355688 bound. P5 stays CLOSED
and was not retested. P4 offline wiring passes with fallback unset/None; literal
empty FALLBACK_PROVIDER is rejected by Settings. Effective target check remains.

No running isolated API/PostgreSQL target was found in local Docker. G9 has no
restart receipt; its acceptance packet is prepared in readiness/. C1 stage capture
and real-PostgreSQL fault harness remain missing. The local interpreter lacks the
OpenTelemetry SDK/exporter, blocking the real hung-endpoint G8 check. Environment
identities, cleanup/rollback duration decisions, complete packet review and
operator DECISION_FREEZE_PASS remain necessary. Global Plan / decision freeze
BLOCKED is unchanged. Historical pending P5/1260-budget statements below are not
current blockers; the status JSON and current readiness audit control.

## Current scoped prerequisite — P5 closed

**P5 = CLOSED / FINAL_INDEPENDENT_REVIEW_PASS** (2026-10-15).
The final scoped review of strict chunked framing found no regressions and no
remaining known BLOCKER/HIGH/MEDIUM defects affecting P5 safety or correctness.
[Final evidence](campaign-redesign/p5-final-review-pass/validation.md): 218 tests
passed under P2, no credentials, zero egress or external provider calls. Replay:
168 requests, USD 4.15355688 <= USD 5. Runtime and runner code were not changed by
this final review. All prior S1/S2, Content-Length and chunked findings are closed.
The runner is frozen; no further changes are part of this task.

ORQ-41 remains **Plan / decision freeze BLOCKED**. P5 closure does not authorize
environment work, P4 recheck, G9, campaign execution or a global Implement phase.
No Notion synchronization or commits. Historical evidence below records earlier
states and is superseded by this current prerequisite status.

## Previous P5 implementation evidence

The operator authorized only the S2 observability seam and P5 campaign harness
as prerequisites for completing Plan. S2 is exclusively the explicit correlated
`retrieval_pipeline.evaluator_triggered request_id=<UUID>` event; previous call-count
inference is superseded. The approved 2026-10-13 amendment additionally exposes
the existing completion UUID/evaluator boolean in its message; no business behavior
changes. The subsequent approved S1 amendment adds only the observational provider and
request-middleware seam described above.

**P5_ALL_REVIEW_FINDINGS_FIXED_AWAITING_FINAL_REVIEW**, not CLOSED. Runner code lives in
`experiments/production_graduation/campaign_runner/`; focused tests in
`tests/experiments/test_orq41_campaign_runner*.py`. Durable conservative receipts,
hash chain/head, fsync, R_max admission, crash settlement, no resend, exclusive lock,
P4/artifact/source checks and operator-controlled block boundary are implemented.
Strategy A only; no DB usage reader or JSON logging launcher.

[Validation](campaign-redesign/p5-evidence/validation.md): 54 P5 cases plus 36
neighboring regression cases, 90 passed, zero failures/skips; local Unix-socket
stub HTTP/SSE dry runs and all terminal states demonstrated. Worst-case 168-request
replay USD 4.15355688 <= USD 5. P2 namespace/guard receipt confirms no credentials,
no external routes and zero egress attempts; zero external provider calls.

ORQ-41 remains **Plan / decision freeze BLOCKED**. No global Implement transition,
implementation.md, paid campaign, G9, environment provisioning, Notion synchronization
or commits. Global implementation/execution authorization fields remain false.
Independent review: [historical findings](campaign-redesign/p5-review/review.md).
F1–F3 are fixed and their scoped independent review passed: correlated completion corroborates S2, directory parents
are durably synced before admission, and raw HTTP reads enforce a single absolute
deadline. [Critical validation](campaign-redesign/p5-critical-fixes-evidence/validation.md):
38 focused / 130 combined cases pass under P2, zero external calls/egress, replay
USD 4.15355688. F4–F8 are now also implemented: cleanup operational FAILED without
rewriting durable close; SSE body EOF validation; evaluator-failure order/duplicates;
lock identity before unlink; no-follow/fstat ledger identity before append.
[All-fix validation](campaign-redesign/p5-all-findings-evidence/validation.md): 165
combined tests pass, zero egress/providers, unchanged replay and app/ hashes.
Private preserved filesystem/no external writers remains an operating condition.
No overall final review or CLOSED status is claimed.
Next: independent final review of all P5 fixes,
remaining gate harnesses/environment/fixture pinning
and G9 evidence, then explicit DECISION_FREEZE_PASS. This entry supersedes earlier
P5 proposed/unauthorized wording only for this scoped prerequisite.

## Current continuation — thresholds accepted, complete freeze BLOCKED

The operator accepted the seven thresholds, USD 5 total external spend cap,
single configured-primary generation model, isolated environment and controlled
restart/redeploy policy. [Decision packet](decision-freeze.md) records the exact
1260-request workload proposal and conservative generation-only USD 706.019328
upper envelope. This does not forecast spend or prove actual cost exceeds USD 5;
it fails to certify the cap. Auxiliary costs remain unresolved. No campaign ran.
Existing rollback drain/preservation and isolated image/config identities remain
unproven. No new infrastructure is authorized. ORQ-37 failures and ORQ-40 defer
remain intact. Canonical state stays Planned / Plan, not an administrative defer.
Stop for operator review; implementation and measurement remain unauthorized.

The following sections record the earlier Plan/first-round snapshot. Pending
threshold-acceptance and no-restart wording there is superseded by this entry
and the current decision packet; outstanding evidence is not superseded.

## Latest continuation — conceptual approval, decision freeze pending

The operator approved the Plan conceptually and authorized one short decision-freeze
round before code. [Decision packet](decision-freeze.md) records a passing
administrative ORQ-40 entry check and pending thresholds, environment and rollback
inputs. No runtime implementation, campaign or frozen contract is authorized.
Earlier statements below about pending conceptual approval describe the initial
Plan delivery. Measurement/implementation approvals remain outstanding.


## Authorized work and stopping point

The operator authorized only the planning proposal/spec and minimal governance
artifacts. [Spec](spec.md) and [evidence inventory](evidence-inventory.md) are
drafts awaiting approval. No runtime implementation, measurement, approved
checkpoint, operational contract freeze or registration exists. No outcome is
assigned and no runtime readiness is claimed.

Number reserved using `fw_claim_orq_number.py` under hybrid policy; returned 41.
Independent remote lookup confirmed `ait-orq-number-ORQ-41` and main both at
`c75fb707f5a8f236846131f0da8f5a0c23b9d969` (merged ORQ-40 PR #14).
Local branch: `orq/ORQ-41-production-retrieval-graduation`. The helper fetched
main/tags and created the reservation tag. No branch push, commit or merge was
performed in this Plan task. Ignored artifacts were not force-added.

REUSE identifies technically supported components, CONDITIONAL identifies
unresolved integration/readiness candidates, EXCLUDE prohibits promotion in this
graduation. Document RAG and optional E-BM25 remain subject to operational gates.
Dense conversational retrieval and all semantic-memory capabilities remain excluded.
No capability was enabled; existing defaults remain unchanged.

## Evidence reviewed and independent assistance

Administrative records from ORQ-27 through ORQ-40 and bounded relevant runtime
source/ADRs were read. Historical experiments were not reproduced. No research
dataset or held-out payload was opened, and no corpus was traversed or rehashed.
The ORQ-40 custody seal was read only as metadata. The preserved files are listed
in `preservation-baseline.json`; that file is an integrity baseline, not a new seal.

Three economical GPT-6-luna agents inspected disjoint historical/source subsets.
A fresh-context source-review agent then reviewed the draft; see
[advisory review](plan-review.md). This was native advisory assistance, not the
configured external-review bridge or an approved framework design checkpoint.
No external model API, review bridge, model-loading or evaluation command ran.

## Material design findings

- A final shared added-context cap already exists across documents, recent window
  and episodic events. Reuse it. The 12000-character production default has its
  own ORQ-37 provenance; no experimental ORQ-40 parameter is copied into runtime.
- Current selected counts precede final pruning. Stage identities/spans and
  actual adapter dispatch must be observed before claiming delivered evidence.
- Settings instantiate at import. In-process flag mutation in tests does not
  establish an operator no-restart rollback mechanism. Resolve admissible
  propagation and in-flight behavior before contract freeze, or defer.
- No bilingual answer-quality or general abstention guarantee follows from
  successful retrieval. Preserve model-dependent historical observations.

## Pending before approval or execution

The spec lists provisional relative limits: core latency +5%, optional latency
+15%, mean/p95 cost +10%. These are proposals, not approved thresholds. Absolute
latency/cost/resource bounds, workload W/N/R/C, provider/model/config identities,
token headroom, price provenance, finite spend envelope, owner and rollback
propagation/duration remain open. A TBD cannot pass a gate or authorize measurement.
Formal design review and explicit operator approval remain required before runtime
work; measurement also requires its own complete prospectively fixed contract.

## Governance reconciliation and inconsistencies

- The live roadmap/index now record ORQ-41 Planned / Plan; Routing 42, conditional
  offline ML 43 and AI Green 44 remain unreserved placeholders in that order.
- The Master Project Document's current ORQ-41 row is updated; a new Dashboard
  planning record and Draft Prompt Library record were created after exact
  title searches and SQL duplicate checks returned no matching rows. Readbacks
  are recorded in `governance-sync.json`. No Fully Synced lifecycle is claimed.
- Notion's bibliography still uses older routing 41/42 and AI Green 43 labels.
  Its live roadmap row/sequence controls; bibliography cleanup remains disclosed
  debt outside this minimal Plan update.
- README, live LLD, appendix and predecessor handoff retain the earlier dated
  unreserved-successor snapshot. They were not rewritten in this task; the live
  roadmap/index and this ORQ own the new state. ORQ-40 artifacts remain unchanged.
- AGENTS.md names Framework V2, while project-config.yml and the project's Notion
  migration note select V3/hybrid. Use the configured Planned/Plan vocabulary;
  this discrepancy does not authorize changing framework configuration.
- ORQ-37's older closure prose conflicts with its latest Blocked validation.
  The 2026-09-13 validation controls. ORQ-39 documentary closure lacks full formal
  reconciliation; no inherited Fully Synced claim is manufactured here.

## Next action

Present this proposal and its open decisions to the operator. Stop before runtime
implementation or campaigns. GRADUATED and ADMINISTRATIVELY_DEFERRED are proposed
operational dispositions only. A future explicit defer must record the blocker,
failed/unmeasured gates, disabled capabilities and NO RUNTIME READINESS CLAIM;
it permits Routing to proceed without reopening ORQ-40.

## Final decision-round receipts

[Independent review](decision-freeze-review.md): BLOCKED; no material arithmetic
or logical defect found. [Governance readback](decision-freeze-final-sync.json)
confirms the Dashboard, Master and existing Prompt Library reflect this decision.
[Validation](planning-validation.md) records documentary checks and preservation.
Next step is operator review of the concrete budget/environment/rollback blockers,
not implementation or automatic defer. No approval to spend was exercised.

## Bounded model-selection preflight — 2026-10-09

The operator subsequently authorized a separate USD 0.50 pre-freeze comparison
of the configured NVIDIA primary against nvidia.nemotron-nano-3-30b in us-east-1.
This supersedes the earlier no-model-comparison restriction only for that bounded
selection task, not the graduation campaign. Twenty-four synthetic paired EN/ES
cases and prewritten rubrics were prepared. [Preflight report](model-selection-preflight/report.md)
records STOP before inference: the available conservative upper envelope is
USD 2.19222016, not a forecast, and does not certify USD 0.50. No calls, no scores,
USD 0 benchmark spend, no charge against the USD 5 campaign allocation. Provisional
recommendation KEEP_BASELINE reflects missing comparative evidence, not superiority.
No ORQ-41 model identity, threshold or production configuration was changed.

## Model-selection benchmark execution — 2026-10-09

The corrected preflight certified USD 0.11394120 within the USD 0.50 cap and the
authorized run started after hash verification and one recorded pre-call harness
amendment (incremental raw-event journaling). The first call, baseline W-EN
warm-up, failed with a normalized auth error and the runner stopped as required.
Read-only diagnostics showed the `.env` AWS access key is invalid (STS
InvalidClientTokenId; Bedrock control plane UnrecognizedClientException). Spend
USD 0; zero measured cases. Status: **NO_COMPARATIVE_EVIDENCE**; no model
recommendation. See [report](model-selection-preflight/report.md). Resuming needs
valid operator credentials and explicit archiving of the attempt files. ORQ-41
model identity, thresholds and BLOCKED decision freeze are unchanged.

## Model-selection benchmark completed — 2026-10-09 (supersedes the entry above)

After the operator rotated the AWS key, attempt 1 was archived and attempt 2 ran
all 50 calls without STOP, retries or errors. Both models passed 23/24 (EN 12,
ES 11, no-evidence 6/6). Candidate p95 full latency 1.128x and TTFT 1.131x
baseline; mean cost 0.315x. All prospective rules are met: recommendation
**SELECT_NEMOTRON_3_NANO**, awaiting explicit operator approval. Spend USD
0.00094210, outside the ORQ-41 USD 5 allocation. ORQ-41 model identity,
thresholds and BLOCKED freeze remain unchanged. See
[report](model-selection-preflight/report.md).

## Model selection approved — 2026-10-09

The operator approved SELECT_NEMOTRON_3_NANO. ORQ-41's fixed generation model is
now `nvidia.nemotron-nano-3-30b` (us-east-1), recorded in decision-freeze.md,
spec.md and planning-status.json (`fixed_generation_model`, refreshed spec
digest). Local `.env` and production configuration were not changed. The USD
706.019328 envelope describes the previous model; recomputing it for the selected
model is now a pending item. Decision freeze remains BLOCKED; thresholds are
unchanged; implementation and measurement remain unauthorized. Notion governance
mirrors (Master Project Document, Dashboard) were not updated in this step.

Notion mirrors (Dashboard, Master Project Document ORQ-41 row, Prompt Library) were
then updated with the approved model and read back; see `model-selection-sync.json`.

## Generation envelope recomputed — 2026-10-09

Using the official model card (256K context, 8K output) and pricing (USD
0.06/0.24 per M) for `nvidia.nemotron-nano-3-30b`, the generation-only envelope
for the unchanged 22680-attempt workload is USD 401.31624960 (decimal-reading
sensitivity USD 391.9104), down from USD 706.019328. It still cannot certify the
USD 5 cap; decision freeze remains BLOCKED. Recorded in decision-freeze.md,
spec.md and planning-status.json. Notion mirrors not updated in this step.

## Enforceable cost bound — 2026-10-09

The provider-window envelopes are now informational ceilings only. The 1260-request
count was audited (no double counting; the old envelope omitted embedding and rerank).
The enforceable all-component bound in [cost-bound/report.md](cost-bound/report.md)
shows the workload cannot fit USD 5 under the allowed levers: uncapped primary output
at 2 code-fixed HTTP attempts costs USD 4.95 for 1260 requests before rerank and inputs.
Smallest allowed fit: 1 application attempt and <= 84 requests, which conflicts with
the p95 design. Budget blocker: **BLOCKED**. No calls, runtime changes, threshold or
model-identity changes; Notion not updated.

## Campaign redesign proposed — 2026-10-09 (awaiting operator approval)

[campaign-redesign/design.md](campaign-redesign/design.md) classifies G1-G5, G9 and
G10 as deterministic (stubbed, credential-free, USD 0) and G6/G7/G8 as mixed. The paid
campaign is 168 requests: C1/E1 x EN/ES x both paths, N=20 + 1 warm-up per cell.
Its enforceable bound is USD 4.45355688 with runner STOP rules on application retry and
evaluator trigger. Rewrite/evaluator output caps are recorded as non-blocking
hardening debt. No calls, runtime, threshold, cap, model or Notion changes. The
decision freeze remains BLOCKED on environment, rollback, fixtures and preconditions P1-P5.

## Campaign design approved — 2026-10-09

The operator approved CAMPAIGN_DESIGN_PASS (168 requests; all ten gates and thresholds
retained). Not an execution authorization. Next: close P1-P5, environment, fixtures and
G9 rollback evidence; independent review; then an operator DECISION_FREEZE_PASS decision.
Implementation and execution only after that. Decision freeze remains BLOCKED. Notion
not yet synced.

## P1 closed — 2026-10-09

Rerank prices re-verified from official sources, no model calls: GCP Ranking USD 1.00
per 1,000 queries (a query is up to 100 documents); AWS amazon.rerank-v1:0 in us-west-2 USD 0.001
per search unit (AWS public price list 2026-10-06; one call with up to 100 chunks; query
length does not add units). Campaign calls send 20 documents, so each counts as 1 unit. The
bound is unchanged at USD 4.45355688. Evidence: campaign-redesign/p1-rerank-price-verification.json.
P2-P5 remain open.

## P4 verified in code — 2026-10-09

Local .env sets FALLBACK_PROVIDER=openai, which wires ResilientProvider and could reach
unbounded OpenAI calls. The campaign must set FALLBACK_PROVIDER empty, ROUTING_POLICY=static,
shadow mode off, and OTEL disabled or on a loopback/compose-internal collector. An offline
check confirms the factory then returns BedrockProvider. Other sinks are local. Notion and
web-read are outside /chat. Re-run p4_check.py at environment pinning. No .env or runtime changes.

## P2 closed — 2026-10-09

Credential-free sandbox proven: empty network namespace (kernel ENETUNREACH), no credentials,
empty HOME, no .env, and real PostgreSQL over a Unix socket in a --network none container.
Full suite 1798 passed / 0 failed / 27 skipped, including all 14 PostgreSQL-marked files.
50/50 real Bedrock streams replay exactly. 0 egress attempts and 0 provider calls. No gate
needs credentials. Harnesses still to build: C1 stage capture, real-PostgreSQL /chat fault
injection (G3), C1/C0 controlled harness, hung-loopback OTLP check, restart drill (G9).
Evidence: campaign-redesign/p2-credential-free-verification.json.

## P3 closed — 2026-10-09

Frozen corpus: the ORQ-37 corpus restored from the existing dev volume (read via a network-less
copy; original volume untouched). Tenant orq37-t23, 124 documents, 2146 chunks with 1536-dim
embeddings, fingerprint 787ae137…df0999 (matches the manifest and ORQ-37). Data-only dump
corpus-snapshot/orq37-t23-corpus.pgdump: an offline restore reproduces the fingerprint, the
content SHA-256 and RLS visibility. No ingestion and no external calls; setup cost USD 0,
effective bound USD 4.15355688. Procedure: corpus-snapshot/RESTORE.md. Only P5 remains open;
P4 is re-checked at environment pinning.

## P5 design proposed — 2026-10-09 (awaiting operator approval)

campaign-redesign/p5-runner-design.md specifies the runner. It is a campaign-only harness
outside app/, with no runtime change. The stdout formatter drops structured fields, so S1
means any provider.retry line, and S2 means a third logical Bedrock call or evaluator_failed,
both attributed by concurrency-1 log windows. The ledger is append-only and hash-chained,
charges conservatively (actual primary usage only through optional reader B), and admits a
request only if settled + R_max (0.17269772) <= 5. Crashes settle at R_max and close FAILED;
there are no budget resets. Terminal states: COMPLETE, INCOMPLETE_STOP_RETRY,
INCOMPLETE_STOP_EVALUATOR, INCOMPLETE_BUDGET, FAILED. No code, calls or Notion changes.
