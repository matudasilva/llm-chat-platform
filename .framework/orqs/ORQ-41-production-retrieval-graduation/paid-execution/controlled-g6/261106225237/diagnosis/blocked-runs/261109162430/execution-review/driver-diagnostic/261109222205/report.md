# Real SQLAlchemy/asyncpg lifecycle diagnostic

**REQUEST_FREE_DRIVER_DIAGNOSTIC_COMPLETE**, 2026-11-09. Thirty adapter calls
completed once: the exact twenty ES-SSE/block0 warmup cases, then the ten ES
SQL diagnostic cases. No /chat, provider, C1 receipt generation or new A/A ran.
The observed cache transition is **5custom executions then25generic** under auto.
This identifies a concrete difference from the prior first-custom-plan SQL probe;
it does not establish the cause of the historical A/A's8.420424% difference.

## Frozen execution and real runtime path

Operator approval: "ok, continuemos con la proxima prueba". Manifest SHA-256:
`506d94f505d90453f994cafab098852b64d3b7e958dc72fa81139d3ce0e54538`. One process, concurrency1, one attempt/slot, fresh UUID5 slot
identities; no retries, repeated run or replacement. Warmup case order, messages,
tenants and the fixed1536-dimensional vector are unchanged from the retained
A/A. The original RAG corpus and shared schema/role/settings procedure were
restored into a new disposable PostgreSQL cluster, with the same seven ANALYZE
statements and pre/post P3/RLS/identity checks. No original database was changed.
Conversation/history/usage tables are empty in this clone because this SELECT
does not read them. Full application data or request processing is not reproduced.

Existing worker image `sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707` and PostgreSQL image `sha256:8e5355e9ff399a002fa46148399a1ac22fb3e9b2d390f857296e6da6b5559ba1` were
reused with pull=never. PG runs networknone/CPUs4,6/2CPU/2GiB; the adapter process
joins only its namespace, CPUs0,2/2CPU/2GiB, no published ports or Docker socket.
No API lifespan, Redis, collector, telemetry exporter or provider is started.
Actual Settings/adapter/session/tenant source hashes were probed in the frozen
image. SQLAlchemy2.0.52, asyncpg0.31.0, greenlet3.5.5 are observed installed versions,
not dependency changes. External credentials/global dotenv remain scrubbed.

The worker calls shipped build_rag_sessionmaker and PgVectorStore.hybrid_search,
with the normal pool_pre_ping/default pools/cache and inferred parameter types.
Each call uses a fresh TenantScopedSession and the existing tenant_scope/after_begin
GUC hook, then rollback/release; one engine persists across all thirty calls.
Actual current_user=session_user=rag_app, non-superuser/non-bypass, row_security on
and expected tenant are checked. Diagnostic transactions are explicitly READ ONLY
with transaction-local statement30s/lock5s bounds and overall35s slot bound.
These guards change no runtime/global or planner setting. Engine dispose is bounded10s.

## Observed cache and parameter identity

All thirty calls reused one backend PID and one hybrid prepared-statement name.
Server metadata was read on that same session before/after each call. Each hybrid
counter total increments exactly once; from_sql=false. No explicit PREPARE,
EXPLAIN, forced plan mode or cache-size override was used. Metadata queries are
separate observations outside the adapter timer and do not match the hybrid
statement selector. No extra hybrid execution occurred while inspecting it.

The driver emitted the exact original SQL with numbered binds in occurrence order:
`query_embedding, top_k, query_text, rrf_k`. Actual inferred types are
`vector,bigint,text,bigint`, captured with the full compiled statement in
compiled-query.sql. This differs from the previous explicitly typed psql wrapper;
no claim of equivalent client signature was made for that earlier probe.

Calls1-5 select custom plans. Call6, warmup ES-history-02, selects the first
generic plan. All remaining calls use generic plans, including all ten diagnostic
cases after the fixed20warmups. Final counters: custom5/generic25. Every case
returns the expected20rows for the corpus tenant or0rows for isolated tenants.
All twenty corpus-visible results have one identical ordered projection hash.
No output or input drift was observed at the transition.

## Adapter-only observations

Wall and process CPU clocks bracket the unmodified hybrid_search call, including
its parameter formatting, SQLAlchemy/asyncpg execution and result mapping.
Checkout/transaction-begin/GUC and rollback have separate coarse aggregate clocks;
identity/cache observations are outside that interval. C1 receipts, HTTP/rewrite/
embedding model/primary generation and SSE are not invoked by this diagnostic.

| Diagnostic case | Adapter elapsed ms | Python process CPU ms | Chosen plan |
|---|---:|---:|---|
| ES-document-01 | 15.808 | 0.459 | generic |
| ES-combined-01 | 24.140 | 0.459 | generic |
| ES-document-02 | 13.494 | 0.409 | generic |
| ES-combined-02 | 22.160 | 0.534 | generic |
| ES-document-03 | 12.001 | 0.446 | generic |
| ES-combined-03 | 19.529 | 0.434 | generic |
| ES-document-04 | 14.646 | 0.487 | generic |
| ES-combined-04 | 22.425 | 0.524 | generic |
| ES-document-05 | 14.728 | 0.493 | generic |
| ES-combined-05 | 23.127 | 0.520 | generic |

Document elapsed mean14.135ms (12.001-15.808); combined22.276ms (19.529-24.140).
Python process CPU means are0.459ms and0.494ms respectively. PostgreSQL CPU belongs
to another process and is not counted here. Wall-minus-CPU is not a measured
network/SQL wait, and no original G6 time is corrected by subtraction.

For identical ES-combined-01 input/output on the same connection, the earlier
custom warmup took7.268ms and the later generic diagnostic took24.140ms.
This is an observed within-run association, not a randomized matched plan-mode
experiment: phase, physical state and time also differ. The adapter-only generic
path nevertheless exhibits substantial elapsed time without C1/SSE/providers;
assigning the historical remaining time to C1 would be unsupported.

## Interpretation and residual limits

The earlier server-only7.49-8.16ms custom-plan results were not a representation
of this warmed driver/cache state. Current metadata resolves that blind spot.
It supports a focused test of custom versus generic SQL execution with the real
inferred types. It does not prove which plans the historical A/A used, because
those original backend cache counters were not retained. Both original A/A labels
used the same image, so a common expensive path alone also cannot establish why
one label's P95 was8.42% higher. Host/scheduler/physical-state variability remains
unattributed, and no performance acceptance criterion is evaluated here.

This diagnostic omits C1/other request work, uses one connection, and adds
identity/cache observations and read-only/timeout guards. These can perturb state;
source/image/data equality and the warmup sequence do not establish exact full
application or CPU-frequency equivalence. R=1/N=5 per diagnostic category does
not support a statistical-equivalence claim. No root cause or runtime fix is
certified. No SQL function is asserted to be repeatedly evaluated inside a plan:
we did not inspect a generic EXPLAIN in this task.

## Validation, retention and next proposal

All30slots resolved PASS, engine disposal succeeded, worker/controller exited0,
raw stdout/stderr are empty except completion status. Retained-record analysis
independently recalculates counter deltas, checks all markers/hash bindings,
source-derived compiled SQL equality, identities and expected outputs. This is
parent verification, not a distinct-review claim. No new pytest or repeats.
Pre/post database corpus/business/schema/settings match; all500protected files
are unchanged. Only the new worker/cluster were stopped, with data/container/
markers retained/nonresumable; historical environment state remains intact.
No source, existing harness, P5, provider/retry/retrieval/persistence/SSE behavior,
global-env/model/threshold/accounting/existing-schema/grant/host policy change.
The only schema/role materialization was the fresh-clone bootstrap.
P2 audit empty/absent; external/provider calls0, application requests0, USD0.
No G9, paid campaign, Notion, commit, push or deployment.

See next-proposal.md for a bounded request-free custom/generic EXPLAIN comparison
using these exact driver-inferred types. It requires separate approval because
this completed manifest preserves auto and forbids forced modes/extra EXPLAIN.
No follow-on query or runtime change is authorized. Preserve AA_CALIBRATION_FAIL,
CONTROLLED_G6_FAIL, paid BLOCKED_CONTROLLED_G6_FAIL and global In Progress /
Implement / DECISION_FREEZE_PASS.
