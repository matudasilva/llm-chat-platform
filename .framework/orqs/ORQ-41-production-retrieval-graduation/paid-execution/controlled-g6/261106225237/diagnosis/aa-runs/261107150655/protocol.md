# Prospective fixed-affinity full-C1 A/A calibration

AA_CALIBRATION_PREPARED_NOT_EXECUTED. Operator approved hardware-audit/proposal.md. This is not an official G6 run and cannot lift paid admission.

## Fixed identity and population

Both labels c0/c1 denote identical optimized C1 images and full C1 behavior, not baseline/candidate semantics. Capture, application/SDK attempts, purpose/invocation lifecycle and hash-chain validation are enabled in both. Local native SDK response transports/embedding/reranking remain deterministic stubs. No extra provider calls or usage occurs.

The unchanged original build_samples population contains420identities per arm:800measured requests plus40document warmups across four language/protocol cells, N=100measured/arm/cell,25each document/history/combined/empty, W=5originaldocument warmups/arm/cell, original balanced arm/cell order, R=1 and one attempt/identity. Conversation/request UUIDs are fresh and paired across arms, databases separate. Exact payload/call parity and840unique valid full-C1 contexts are mandatory. No changed warmup order/composition or new crossover is used in this A/A.

Original ASGI-ingress to primary serialized native-send entry is the timing interval. Primary capture bookkeeping follows the endpoint. Clock placement equals the reviewed original worker. Coarse cgroup/topology reads occur before/after a cell outside request timing. No fine profiler wrappers, sleeps/cooldown, CPU-governor change, realtime priority or observer disabling.

## Resource environment

Both serial API arms use CPUs0,2, distinct physical cores with the same reported5.6GHz maximum. Dedicated PostgreSQL uses4,6. All retain2CPU quota/2GiB memory+swap limit. Configured and effective cpusets/affinity/cpu.max are verified before admission and after each cell. Topology/governor must match the frozen plan. Affinity is not exclusive ownership, fixed frequency or isolation from other SMT siblings/host activity; these limitations remain.

The shared historical cluster/services are untouched. A new private-password cluster clones the existing schema and P3, with source database locale/encoding explicitly retained and identical roles initialized by the unchanged scripts. Redis/OTLP clones use their existing immutable images/config/caps in the dedicated network-none PostgreSQL namespace; no published ports, downloads or outside exporter. OTLP config exports only to local debug output. P2 guard, empty global dotenv and absent external provider credentials apply. Dummy signing values exist only inside the existing memory-native stub client.

Worker cgroup cpu.stat before/after each cell retains all counters; PostgreSQL cell counters are also recorded. Validate monotonic counters; never infer per-request throttling from aggregate counts or subtract throttled time from p95. Core selection failure, resource drift, incomplete/failed functional or evidence checks, payload mismatch or network audit attempt invalidates the experiment. No automatic retry/resume; exclusive execution-started.json binds the admitted run.

## Acceptance and follow-up fixed before execution

Require complete840rows and all integrity checks, exact post-run persistence, P3/RLS/schema/config parity and empty P2 audit. Nearest-rank p95 for100 is sorted index94; retain p50/p95/p99/max and raw durations. Each cell passes A/A only if p95(A)*100<=p95(B)*105 AND p95(B)*100<=p95(A)*105. All four must pass for AA_CALIBRATION_PASS; otherwise AA_CALIBRATION_FAIL. Zero requires zero. This symmetric calibration criterion was expressly approved; it does not alter the original one-sided C1/C0 G6 threshold. Driver exit0 means result publication, not PASS.

R=1 is a minimum calibration, not a statistical equivalence or long-term stability proof. If A/A fails, record that this environment/protocol did not demonstrate precision sufficient for5%source attribution in this run; preserve G6FAIL. Do not optimize application functions based on A/A or mark historical G6INVALID. If it passes, propose a fresh pinned C0/C1 formal run with original criteria for separate approval/review; do not execute it automatically. No favorable-run selection or retrospective sample exclusion.

## Preparation validation and retained failure

55author controls PASS in the pinned C1 Python3.13.15 image/network-none/P2: symmetric boundary/reverse/zero checks, full-C1 both arms, identities/parity/population, affinity/topology/counter drift, schema whitelist and original G6 regressions. controls.xml retained; existing pytest-asyncio warning remains.

Initial preparation261107141146 stopped before any API at strict raw schema comparison. Source and roundtrip differ only in the exact previously reviewed feedback CHECK array-cast deparse forms. Dumps/diff/summary retained under that packet; only its three own containers were stopped (not removed), leaving data/evidence intact and avoiding background load. No sample or performance trial existed. New preparation uses exact full-line whitelist from prior seeded-fixture review: one constraint only, all other DDL bytes must match. Real readonly expressions/truth tables/roles/locales are corroborated before review. No schema/grant/constraint changed to obtain equality.

Prepared data proof:420conversations/9600history messages per arm, exact case content/order/deterministic UUIDs, P3 content/fingerprint, own/foreign RLS and normalized effective configuration equality. Final proof must confirm420conversations/10440messages per arm, exact9600history plus one user/assistant exchange per conversation (840newcanonical UUIDs normalized only for paired comparison), unchanged corpus/schema/roles/config. Parent SQL execution is separately attributed; distinct review does not claim independent DB connections.

## Scope

Only aa_calibration controller/worker/resources, focused tests and evidence/environment manifests are new. App/P5/provider behavior/retry/retrieval/SSE/persistence/schema/global-env/model/threshold/accounting unchanged. No G6/G7 live providers, campaign, G9, Notion, commit, deployment or paid spend. Global Implement/DECISION_FREEZE_PASS, official G6FAIL and paid block stay fixed. Independent harness/plan review is required before execution; post-run review is separate.
