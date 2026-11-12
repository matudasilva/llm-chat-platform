# Independent workload lifecycle design review

Result: **WORKLOAD_LIFECYCLE_DESIGN_REVIEW_PASS**, design consistency only. Operator approval of the four explicit decisions remains required. No implementation or host/workload execution is authorized by this receipt.

## Reviewed contract

The proposal correctly separates the existing empty-slice administrative normal-path proof from a populated workload lifecycle. It preserves the old helper/receipts and requires a new sealed supervisor/timer contract; it does not run a workload under the old300s timer. The7200s nonrenewable admission/reservation cap includes preparation, does not guarantee completion or relax the fixed1440 population, and cannot turn an incomplete trial into a performance failure/retry permission. Existing300s request/10s nested cleanup semantics and the metric boundary remain unchanged.

Durable STOP and admission are serialized by a supervisor, not a polled mutable file. A committed permit is an admitted request even if its acknowledgment or consumption proof is lost; no second permit can be issued while unresolved. Expiry/identity loss/late supervisor evidence closes admission. Root ownership, exact run/container/image/network/cgroup/PID/starttime/boot identities and authenticated local peers constrain action ownership. Restart is recovery-only. No arbitrary command interface, workload Docker privilege or shared-container mutation is proposed.

The390s drain interval is explicitly an observation budget, not a proof of cancellation or guaranteed shutdown; it accounts for the remaining one permitted request, finalization and graceful PG handling. Hung/uninterruptible work, unknown command outcomes, foreign descendants or shutdown failure lead to durable FAILED/NOT_DRAINED, retain reservation/data and require operator reconciliation. Graceful stop never silently escalates to SIGKILL. API exit/DB-client drain precede owned smart PG shutdown. An auxiliary housekeeping failure may coexist with safe CPU restoration only after actual benchmark populated0; overall lifecycle still fails. The60s restoration limit is a success criterion, never permission to abandon half-restored state. Metric and lifecycle receipts remain distinct.

## Conditions carried into implementation review

The source implementation must prove, with deterministic IPC/clock/journal/process doubles, every acceptance-matrix case before a separate real no-benchmark lifecycle drill: exact bounded peer protocol, PID/starttime and socket replacement checks, write-ahead permit/STOP durability and one-use consumption, command timeout reconciliation, preservation of incomplete-block evidence, supervisor/timer restart recovery-only, no admission after unknown outcomes, and interruption-safe owned drain/restoration. Single-use expiry must be checked outside the unchanged measured interval; any consumed/unknown permit remains accounted as admitted and is never recycled. OS starvation or inability to drain cannot be converted into a timeout-based process-death assumption. The admission deadline must be tied prospectively to a monotonic boot identity and cannot renew through restart or packet edits.

These are consequences of the written design, not new architecture or extra numerical bounds. Exact service signals, helper/unit/IPC manifests and ownership proofs must be fixed and independently reviewed before any live operation. Full placement/profile checks remain per-worker boundary observations; they do not prove interval-wide exclusivity or attribute latency differences causally. No latency correction, sample selection, relaxed threshold or new provider usage is introduced.

## Approval and limits

The four pending operator decisions are:7200s plus the proposed observation/permit/drain/restoration bounds; local supervisor/one-shot timer plus optional dedicated worker permit seam/new sealed helper; graceful exact-owned-service stopping with NOT_DRAINED intervention; and P2 implementation/tests/independent-source-review only. None authorizes service provisioning, host application, a no-benchmark live drill,1440requests, formal G6 or paid campaign. Those later steps still require separate exact reviewed artifacts and authorization.

No B/H/M design contradiction was identified in this bounded read-only review. No source, host, service, Docker, SQL, API, provider/network or testing operation was performed; only these review artifacts were written. G6FAIL and paidBLOCK remain unchanged. Prior helper/source reviews remain historical and are not implicitly superseded by this proposed design.

Additional retained proposal.json inspected: exact markdown hash, prior binding-review hash and all three current source identity hashes independently recompute; population arithmetic and prospective numeric limits agree. This is file-only evidence validation, not a source implementation review or live operation.
