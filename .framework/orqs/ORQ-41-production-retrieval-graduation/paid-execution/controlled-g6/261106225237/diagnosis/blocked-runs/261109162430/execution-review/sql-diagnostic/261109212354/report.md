# Request-free SQL diagnostic: complete; original A/A cause unresolved

**REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE**, 2026-11-09. All ten approved cases
completed once in a fresh disposable PostgreSQL cluster. This is diagnostic
evidence, not G6, a new A/A, an application fix or paid admission.

## Frozen scope and environment

Operator approval: "ok, avancemos con el planç", accepting the preceding
request-free read-only diagnostic for five ES document and five ES combined cases.
Manifest SHA-256: `ccff45b3e02a19d8d45c2a86a4356ed58ee4c2f6c0ec3b85dad2cef3407efbbe`. The prior A/A plan remains
`b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b`.
One attempt/case, C=1, no warmup, no retry/replacement. Case order was fixed before
execution: document01, combined01, through document05, combined05.

Existing image `sha256:8e5355e9ff399a002fa46148399a1ac22fb3e9b2d390f857296e6da6b5559ba1` was reused with pull=never. The only new service was
`orq41-sql-261109212354-postgres`, network none, CPUs4,6, 2CPU/2GiB, no published ports. No API, Redis,
collector or provider was instantiated. Fresh random local credentials live only
in a private /tmp directory; external credentials/global dotenv were scrubbed.

The clone used the unchanged source schema/locale/role initialization and frozen
P3 dump. It contains124 documents/2146 chunks with the expected content SHA-256,
and zero conversations/messages/usage_events/rag_request_metrics. The same seven
table ANALYZE sequence and unchanged statistics/autovacuum/planner settings were
verified before cases. Preflight reads warmed corpus pages; this is not a cold
cache benchmark. Existing source/old A/A data were never restored over or altered.

## Exact SELECT and actual identity

query-template.sql is extracted directly from PgVectorStore.hybrid_search.
query-prepared.sql changes only named placeholders into numbered placeholders.
Each case uses its unchanged message (the local A/A rewrite returns that message),
the exact fixed1536-dimensional local-stub vector, top_k20 and rrf_k60.
No rewrite/embedding/evaluator/primary generation was invoked.

Each psql connection actually logs in as rag_app: current_user=session_user,
NOSUPERUSER/NOBYPASSRLS, row_security on, app.tenant_id=orq37-t23. Every diagnostic
transaction is READ ONLY and rolled back. Negative/empty tenant checks see0chunks;
the intended tenant sees2146. No superuser SELECT is substituted for these ten
executions. Additional administrative/bootstrap/identity queries are setup proof,
not additional diagnostic executions of the hybrid SELECT.

Session-local PREPARE(text,text,integer,integer) is followed by exactly one
EXPLAIN(ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) EXECUTE. Statement timeout30s and lock
timeout5s are safety bounds only on this diagnostic transaction, not campaign
thresholds or runtime settings. Each statement starts with zero generic/custom
executions and ends with one custom/zero generic, with plan_cache_mode unchanged
at auto. Output root rows are20 for every case. Raw SQL, stdout/stderr, metadata,
prepared counters and JSON plans are retained per case under exclusive markers.

## Observations

| Case | Planning ms | Server execution ms | Output rows | Plan |
|---|---:|---:|---:|---|
| ES-document-01 | 0.998 | 7.661 | 20 | custom |
| ES-combined-01 | 0.940 | 7.726 | 20 | custom |
| ES-document-02 | 0.975 | 7.663 | 20 | custom |
| ES-combined-02 | 0.941 | 7.761 | 20 | custom |
| ES-document-03 | 0.897 | 7.761 | 20 | custom |
| ES-combined-03 | 0.923 | 7.765 | 20 | custom |
| ES-document-04 | 0.968 | 8.157 | 20 | custom |
| ES-combined-04 | 0.951 | 7.492 | 20 | custom |
| ES-document-05 | 0.945 | 7.832 | 20 | custom |
| ES-combined-05 | 1.035 | 8.094 | 20 | custom |

Document mean execution7.8148ms; combined mean7.7676ms (five distinct cases each,
not repetitions). These means are descriptive only. The observed server execution
range is7.492-8.157ms; planning0.897-1.035ms. No performance PASS is inferred.

All ten have the same structural plan: semantic sequential scan of2146chunks,
sort/window/limit; keyword sequential scan of2146rows with zero matches; hash
join and final sort/limit. Sorts are in-memory. Root buffers report6985shared hits,
0shared reads/writes and0temporary reads/writes. The semantic scan is the largest
scan node (about6.0-6.5ms). Node durations are inclusive and must not be summed.
The Seq Scan node is not itself a defect or authorization to add an index.

## Interpretation and blind spots

This server-only, first-custom-plan diagnostic does not reproduce the30-32ms
rag.retrieve wall intervals seen in the six high c1 A/A requests. It did not show
a combined-only server execution penalty under this protocol. It does **not**
prove PostgreSQL was fast during the historical run or attribute the remaining
time to C1. No subtraction/correction of the original primary timing is valid.

The original interval also contains SQLAlchemy/asyncpg setup/pool/protocol work,
result mapping, local embedding and C1 document receipt work. Original prepared
parameter types and custom/generic plan choices after20warmups were not retained.
This diagnostic explicitly declared parameter types; it is not proof of the
original driver's inferred signature/cache behavior. EXPLAIN adds instrumentation,
uses fresh sessions and a new clone with newly collected statistics/cache state.
There is one observation/case, no process/C1 CPU separation and no wall-time
reproduction. The image/schema/P3/settings match does not establish equivalent
physical or prepared-plan state. Root cause remains unresolved.

## Errors, verification and disposition

A file-only authoring check initially failed with KeyError(casefile_sha256):
the script looked up the older A/A key rather than the balanced manifest's
support_files_sha256 entry. It failed before allocating a run/cluster or executing
SQL. The exact source/error and correction are retained in ../authoring/. The
correct existing cases.json digest was then verified; no guard or evidence was
relaxed. The frozen diagnostic itself has10resolved/10PASS/0failed/0unresolved
cases and controller exit0, without repeats. Both controller and case streams
are retained. analyze_results.py independently decodes the retained records and
checks SQL markers, read-only role/tenant/settings, plan counters, hashes and data.
This is parent verification, not a distinct-review claim.

Postflight confirms unchanged corpus/business data/schema/settings and all500
protected source/test/global-env files. Only the new cluster was stopped; data,
container and markers remain retained/nonresumable. environment-final.json also
confirms old A/A services remain stopped and source PG remains running with the
same identity. P2 audit empty/absent; external/provider calls0, app requests0,
spendUSD0. No app/P5/existing-harness/query-policy/model/threshold/accounting/
global-env/schema/grant/host-policy change, G9, Notion, commit or deployment.
The only schema/role materialization was the approved fresh-clone bootstrap;
no existing database schema or grants were modified.
No pytest or new A/A was run.

Next recommendation, not executed or authorized: prepare a narrowly bounded
request-free reproduction through the existing SQLAlchemy/asyncpg path, preserving
normal parameter inference and auto plan-cache behavior, with the original fixed
warmup sequence. Capture cache/parameter metadata and adapter-only timings before
considering any C1 or retrieval optimization. Freeze its exact volume and scope
before any further query execution. This targets a concrete missing comparison
without another full /chat A/A or provider call; it cannot automatically certify
G6. Any instrumentation or runtime change needs separate approval.

Preserve AA_CALIBRATION_FAIL, CONTROLLED_G6_FAIL, paid BLOCKED_CONTROLLED_G6_FAIL
and global In Progress / Implement / DECISION_FREEZE_PASS. No root cause or fix
has been certified by this diagnostic.
