# Measurement calibration before further G6 remediation

Status: READONLY_AUDIT_COMPLETE / A_A_CALIBRATION_PROPOSED_NOT_AUTHORIZED.

## Observations

The host reports Intel Core i9-14900HX, 32 logical CPUs and 24 physical cores. Current sysfs topology distinguishes CPUs0–15 with SMT sibling pairs and maximum frequencies5.6–5.8GHz, and CPUs16–31 without sibling pairs at4.1GHz maximum. The current governor is powersave. These are reported maximum frequencies and topology, not measured operating frequencies or throughput.

Retained formal G6 containers C0/C1 and PostgreSQL all have NanoCpus=2000000000 and empty CpusetCpus. Thus the configured CPU consumption quota does not select identical physical CPUs or a homogeneous CPU group. The frozen controllers specify --cpus=2, without --cpuset-cpus. Previous receipts contain no per-request CPU placement, effective affinity, CPU-throttling or thermal/frequency tape. We cannot reconstruct which CPUs ran historical samples or prove that migration caused the FAILs.

The later diagnostic source contrasts reverse sign without a corresponding runtime change. That is evidence to calibrate the measurement instrument; it is not evidence that the original observed failures were false or that the reviewed candidate has passed. The earlier recommendation to amend warmup/order should remain pending until this additional confound is assessed.

## Smallest useful next experiment

Use an A/A control before another C0/C1 formal comparison. Both arms must use the exact optimized C1 image4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707, full Capture/accounting and identical settings/resources. Merely putting the same image into the old C0 label with candidate=False is not an A/A control: both arms must activate the complete C1 observer/scopes/attempt checks.

Keep the original formal G6 measurement population and protocol for this calibration: N=100 measured per arm/language/path, four equally represented document/history/combined/empty categories, five separate original document warmups per arm/cell, original boundary and fixed balanced source order. This is840local requests (800measured+40warmups), R=1, fresh paired fixtures and separate databases, one prospective attempt per identity. Keeping the warmup/schedule unchanged avoids simultaneously varying warmup, order, code and hardware controls. The later crossover remains retained descriptive evidence.

Pin both sequential API arms to the same two logical CPUs on distinct physical cores from one topology group. A concrete current candidate is CPUs0,2 (separate physical cores, reported5.6GHz maximum); never select SMT siblings as if they were independent physical cores. Pin a dedicated disposable PostgreSQL clone to a disjoint pair, for example4,6, with its existing two-CPU/two-GiB limits and immutable image/P3/schema. Do not mutate the shared historical PostgreSQL container or host governor, disable host tasks, reserve CPUs system-wide, or use realtime priority. CPU affinity does not guarantee exclusive use or constant frequency; record those residual limits.

Verify configured and effective cpusets, image/config/source/fixture identities and exact P3/RLS/business/schema parity before admission. Retain worker cgroup cpu.stat before/after each cell to expose throttling, plus current topology/governor and affinity. Use only coarse existing clocks; no new fine profiling or forced sleeps. The harness change stays isolated outside app/ and requires prospective independent review.

## Prespecified disposition to approve

The calibration asks whether identical binaries can be distinguished by more than the G6 tolerance. A proposed symmetric per-cell A/A acceptance rule is both p95(A)*100 <= p95(B)*105 and p95(B)*100 <= p95(A)*105. This is a new calibration rule requiring operator approval; it does not alter the approved one-sided C1/C0 G6 threshold. Require complete functional/evidence/transport/persistence/P2 checks before interpreting either inequality. Never repeat until favorable or drop samples. R=1 is a minimum check, not proof of long-term stability or statistical equivalence.

If A/A fails, classify the environment/instrument as not sufficiently calibrated for attributing a5% source difference; preserve G6 FAIL and diagnose resource effects or propose another homogeneous environment. Do not optimize application functions or mark G6 INVALID from the calibration alone.

If A/A passes, propose one fresh, independently reviewed C0/C1 run using the same fixed-affinity environment and original G6 criteria. A/A PASS does not certify C1 latency or authorize that formal execution by itself. Any formal environment amendment must be approved and bound prospectively; no historical result is overwritten.

## Authorization and cost

Only the read-only hardware audit has run. No benchmark, new API request, CPU-affinity change, container resource update, PostgreSQL clone, provider call or paid campaign ran during this audit. External spend isUSD0. No app/P5/model/threshold/accounting/schema/global-env change, Notion or commit.

Pending approval: isolated A/A harness and dedicated local resource pinning;840credential-free local stub requests; the symmetric calibration rule; independent review before execution. Hardware audit evidence is audit.json, reproduced by audit.py (sysfs plus read-only Docker inspect). Official G6 FAIL, paid-admission block and global Implement / DECISION_FREEZE_PASS remain unchanged.
