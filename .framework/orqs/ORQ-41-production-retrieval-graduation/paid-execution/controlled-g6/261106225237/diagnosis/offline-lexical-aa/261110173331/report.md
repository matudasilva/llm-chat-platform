# Retained lexical-image A/A: bounded offline diagnosis

2026-11-10. **OFFLINE_DIAGNOSTIC_COMPLETE_CAUSE_NOT_IDENTIFIED**.
The operator authorized the previously proposed retained-data-only diagnosis.
No new request, benchmark, application/harness change, Docker/SQL operation,
service restart, image, host tuning, formal G6 or paid execution was performed.
This report is a new evidence lane; the original execution packet is immutable.

## Population, checks and unchanged decision

`analyze.py` uses only the Python standard library and retained files, under P2
with an empty network namespace, disabled credential/dotenv discovery and the
existing socket guard. It verifies all 173 retained artifact hashes (including
the original final completion), all 505 protected source/configuration hashes,
the exact approved plan/result digests, sample pairing, timing arithmetic and
all original pooled p95 decisions. No application/provider module is imported.

A separate standard-library `verify.py` cross-checks the p95 using cumulative
rank counts, category/case populations, tail concentrations and unchanged
artifact/source hashes: **757 checks PASS**. This is a second calculation, not
an independent human/agent review. Exact P2 commands and exit codes are retained
in `commands.json`; `verification.json` binds the analyzed result.

All 1,440 functional PASS records remain: 800 measurements, 640 warmups, 32
workers and 1,440 distinct C1 accounting instances. Admission uniqueness is
`(arm, request_id)`; paired arms intentionally share their sample/request UUIDs
in separate databases. Both arms use the same image and full-C1 behavior.

| Cell | A p95 ms | B p95 ms | Symmetric gap | Frozen decision |
|---|---:|---:|---:|---|
| EN JSON | 14.642350 | 14.444318 | 1.3710% | PASS |
| EN SSE | 15.134931 | 14.790465 | 2.3290% | PASS |
| ES JSON | 16.155431 | 14.904832 | 8.3906% | FAIL |
| ES SSE | 14.462488 | 16.463800 | 13.8380% | FAIL |

Exactly 100 measured samples per arm/cell, nearest-rank p95 at zero-based index
94 and both original integer inequalities are preserved. The analysis neither
excludes observations nor promotes category/block/order statistics into gates.
Six observations at ranks 95 through 100 are described below; these include
the p95-defining observation, not six independent estimates of p95.

## What the retained samples establish

1. **ES JSON A's tail is concentrated in block 1:** five of the six highest
   durations are in that worker; the sixth is in block 3. The p95-defining
   sample is `ES-json/b1/measured/17`, case `ES-combined-01`, 16.155431 ms.
   The tail includes four different combined cases and one document case.
   B's tail is distributed across blocks 1, 2 and 3. This identifies the
   observations that produce the asymmetric pooled tails, not their cause.
2. **ES SSE B's entire top six is in block 0:** three document and three
   combined cases, ordinals 2, 4, 6, 8, 10 and 12. The defining sample is
   `ES-sse/b0/measured/8`, case `ES-document-03`, 16.463800 ms; its worker's
   maximum is 24.412984 ms. These samples follow all 20 representative warmups;
   they cannot be silently relabeled as warmups. A's top six span all blocks.
3. All eight arm/cell tails comprise document or combined cases. Those paths
   are generally slower than history/empty cases in both EN and ES. Category
   populations are paired and balanced; the failed tails do not isolate one
   broken business case or prove a Spanish-language implementation defect.
   Block populations have 25 samples and slightly different category counts;
   block medians are not interchangeable homogeneous-workload estimates.
4. Matched sample comparisons show B slower in 53/100 EN JSON, 53/100 EN SSE,
   52/100 ES JSON and 62/100 ES SSE observations. ES JSON's median paired
   B-minus-A is +0.075436 ms even though B's pooled p95 is lower. ES SSE's is
   +0.3014325 ms. These descriptive facts caution against equating a tail gap
   with a uniform change to every request. Pairing does not eliminate temporal
   confounding and supplies no alternative acceptance rule.
5. Execution order supplies no universal explanation: ES JSON A's dominant
   tail block runs second, whereas ES SSE B's dominant tail block runs first.
   Passing EN controls also have block variation. No order-based correction
   or removal is justified by these observations.

`analysis.json` retains ranks 90 through 100, every p95-defining sample UUID,
all category/case/order distributions, paired differences and all 32 worker
resource observations. Smaller strata are exploratory and have few samples.

## Resource observations and limits of attribution

- No API or PostgreSQL cgroup CPU throttling was recorded in any observed
  worker delta. Both databases' `blks_read` deltas are zero throughout. These
  counters do not exclude scheduling delays, cache/memory effects, background
  activity or other I/O; zero PostgreSQL physical-block reads is not zero I/O.
- Recorded host-frequency endpoint snapshots range from 735,876 to 4,989,322
  kHz; the pinned governor is `powersave`. A Docker CPU affinity is not proof
  of exclusive host-core isolation or fixed operating frequency. Endpoint
  samples do not measure frequency during the p95-defining requests, so this
  remains a hypothesis to test, not an identified root cause.
- Two observed maintenance timestamp changes concern `usage_events`
  auto-analyze, during B ES JSON blocks 0 and 2 (one concerns the other arm's
  database). They are not in the two workers with the dominant failed tails.
  Their presence provides no request-level causal attribution, and they do
  not prove absence of all background work elsewhere.
- API and PostgreSQL CPU deltas cover full workers: 20 warmups, 25 requests,
  untimed response processing, telemetry and cleanup. PostgreSQL cgroup CPU
  also covers the shared cluster. These numbers must not be subtracted from
  the pooled pre-dispatch intervals or labeled per-request CPU/wait time.

**Evidence gap:** the retained records do not separate per-request retrieval
SQL, connection acquisition, Python assembly/serialization and scheduling
waits. They therefore cannot establish which component caused either tail
cluster. No single causal fix can honestly be selected from this data alone.

## How established projects approach the problem

- [pyperf system guidance](https://pyperf.readthedocs.io/en/latest/system.html)
  distinguishes CPU pinning from isolation and documents frequency/power,
  affinity, topology and system-noise controls. These are candidate mechanisms
  to investigate, not proof of the cause of this run or authorization to tune
  this host.
- [WordPress performance guidance](https://make.wordpress.org/performance/handbook/measuring-performance/best-practices-for-performance-measurement/)
  uses consistent/local setups and combines broad timings with granular
  profiling. It explicitly describes variability even for identical code.
- [PostgreSQL EXPLAIN guidance](https://www.postgresql.org/docs/17/using-explain.html)
  warns that instrumentation itself adds overhead. A diagnostic profile should
  be kept separate from acceptance measurements.

Our existing SQL mechanism/equivalence evidence and image pin remain valid as
their own evidence. The A/A result is about reproducibility of identical arms,
not C1 overhead against C0. A/A FAIL does not prove that the vector database
choice or RAG functionality is defective. The current adapter already uses
PostgreSQL/pgvector semantic search combined with PostgreSQL full-text search.

## Bounded next proposal; no execution authorized here

Before another A/A or application optimization, design one local-only diagnostic
that distinguishes per-stage wall time from process CPU and scheduling/DB
waits on the existing document/combined workloads, with EN controls and both
JSON/SSE. First inventory reusable timing hooks and state exactly what cannot
be observed without a small test-harness seam. Set the hypothesis, prospective
cases/volume, identities, overhead check and stopping rule before requesting
implementation/execution approval. Keep diagnostic instrumentation out of the
acceptance interval or explicitly label that experiment non-gating.

Do not automatically rerun A/A, increase its sample volume, change p95/thresholds,
select favorable repeats, migrate the database or tune the host. If environment
control is proposed, specify reversible isolation/frequency changes or a
dedicated benchmark host and their verification before approval. A future
measurement design change would require a prospective amendment; the present
FAIL cannot be retrospectively rescued.

## Preservation

Task provider spend USD0; zero new local/paid/provider requests, Docker/SQL
operations and validation network attempts. External documentation was read
separately through the research connector, outside the isolated validation;
this is not a claim of zero network traffic by documentation tools.

No app/P5/harness/test/model/threshold/accounting/concurrency/schema/grant/global
`.env` change. All prior failures retained. Keep global
**In Progress / Implement / DECISION_FREEZE_PASS**, official
**CONTROLLED_G6_FAIL** and **BLOCKED_CONTROLLED_G6_FAIL**. This is a completed
offline diagnostic with a precise evidence gap, not a new gate PASS or an
independent review by another agent. No campaign, G9, Notion update or commit.
