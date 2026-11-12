# Matched custom/generic SQL plan comparison

**REQUEST_FREE_PLAN_COMPARISON_COMPLETE**. Twenty approved EXPLAIN executions
completed once with zero errors. Generic mode was slower in all ten matched
cases. Its excess observed elapsed time is concentrated in the keyword scan,
where the plan retains parameterized plainto_tsquery rather than a literal
precomputed tsquery. This establishes a local plan-dependent cost under this
probe; it does not certify the cause of the historical A/A8.420424% label gap.

## Frozen scope and unchanged environment

Operator "continuar" approved the exact preceding20-query proposal, SHA-256
`e780546765695bfb14f5827e9c5f5ac3f9f0fdb6af0769a2c9f9e2aa601d3d7a`.
New manifest SHA-256: `3227898489efda84b4f53ea561119eb4c305f7d3dec15dac76ca9f04484434a2`. Original proposal/driver/A/A artifacts
remain immutable. New isolated PG-only cluster `orq41-plans-261109225659-postgres` reused image
`sha256:8e5355e9ff399a002fa46148399a1ac22fb3e9b2d390f857296e6da6b5559ba1`, pull=never, networknone, CPUs4,6/2CPU/2GiB/no published ports.
No application/adapter process, /chat, provider or new A/A ran.

The clone restored the unchanged shared schema/roles/locale and exact P3 corpus
(124documents/2146chunks); conversation/history/usage/metrics tables remain empty.
The fixed seven ANALYZE statements and original planner/autovacuum settings were
verified before and after. Proof reads warm corpus pages. No cold-cache, physical
state, exclusive-host or fixed-frequency equivalence claim is made.

Every execution logs in as actual rag_app (current_user=session_user), with RLS
on, non-superuser/non-bypass and tenant orq37-t23. It is inside READ ONLY and ends
with rollback/disconnect. Negative tenant controls remain0rows. The only
planner intervention is SET LOCAL force_custom_plan or force_generic_plan in
those twenty disposable sessions. Other settings match the original snapshot;
new ordinary connections and postflight preserve auto. No global/role/env or
runtime planner default was modified.

## Exact inputs and admission

The full captured asyncpg compiled SQL is unchanged, SHA-256
`baf73363e8bc6736ee0713ec99f0872ce3b6e89f16c6acaee3d76237caf1df4c`.
PREPARE uses the actual driver signature vector,bigint,text,bigint and argument
order embedding/top_k/query/rrf, with the retained fixed1536-vector, exact query
messages, top_k20 and rrf60. This corrects the type/signature blind spot of the
earlier explicitly typed psql probe; it does not rewrite SQL or change retrieval.
Each case/mode has an exclusive fsynced admission marker, exact program hash,
raw stdout/stderr, role/settings metadata, selected-mode counters and full plan.
All twenty sessions have distinct backend PIDs and exactly one appropriate
prepared execution (custom1/generic0 or custom0/generic1), from_sql=true.

The approved order was followed exactly: document01/combined01 through05, with
custom first in odd pairs and generic first in even pairs. Thus document cases
are custom-first and combined generic-first. Overall mode order is balanced but
category/order are confounded. There are no warmups, exclusions, resends,
replacements or favorable repetitions. Statement30s/lock5s are local diagnostic
bounds; no campaign threshold changed.

## Observed server and keyword-node times

| Case | Custom execution ms | Generic execution ms | Custom keyword ms | Generic keyword ms |
|---|---:|---:|---:|---:|
| ES-document-01 | 7.902 | 22.917 | 0.717 | 14.858 |
| ES-combined-01 | 8.366 | 27.272 | 0.869 | 19.776 |
| ES-document-02 | 8.429 | 18.235 | 0.694 | 10.255 |
| ES-combined-02 | 7.973 | 24.255 | 0.724 | 17.256 |
| ES-document-03 | 8.585 | 14.453 | 0.707 | 7.342 |
| ES-combined-03 | 8.600 | 23.776 | 0.780 | 16.047 |
| ES-document-04 | 8.495 | 17.195 | 0.698 | 9.915 |
| ES-combined-04 | 7.937 | 25.838 | 0.730 | 18.114 |
| ES-document-05 | 8.145 | 17.995 | 0.667 | 10.346 |
| ES-combined-05 | 8.218 | 26.384 | 0.842 | 18.867 |

Document execution means: custom8.3112ms / generic18.1590ms.
Combined execution means: custom8.2188ms / generic25.5050ms.
These are descriptive five-case means, not metric acceptance or significance tests.
Custom full execution spans7.902-8.600ms; generic14.453-27.272ms. All output
cardinalities are20. Shared block reads and temporary reads/writes are zero.

Both modes scan2146corpus rows semantically and remove2146rows in the keyword
filter, returning zero keyword matches for these ES inputs. The semantic scan
stays about6-7ms. Generic document keyword scans take7.342-14.858ms versus
custom0.667-0.717ms; combined keyword scans16.047-19.776ms versus0.724-0.869ms.
Node durations are inclusive and must not be summed as independent costs.

The custom keyword Filter contains a literal tsquery (for example a sequence
of normalized ES lexemes). The generic Filter retains:

    search_vector @@ plainto_tsquery('english'::regconfig, $3)

All ten pairs show this expression difference, with the extra time localized to
the same scan node. This supports targeting tsquery computation in the generic
path. Exact function-call counts were not instrumented: do not claim a measured
2146calls or attribute every elapsed nanosecond to that function. Mode changes
can affect other planning expressions too, and elapsed time includes scheduling.
Full predicates/plan nodes remain in analysis.json and raw case plans.

## What is established and what remains open

The current query shows a consistent local performance difference across modes in
these20forced-mode observations, without C1/SSE/provider work. The preceding
driver-only30-call probe showed auto selecting5custom then25generic using the
same source/data/types, which makes this a concrete production-path hypothesis.
The historical A/A did not retain backend plan counters, and both A/A labels
used the same image. These results do not prove which original calls used which
plan or explain the8.42% difference between labels. Original AA_CALIBRATION_FAIL,
CONTROLLED_G6_FAIL and paid BLOCKED_CONTROLLED_G6_FAIL remain valid.

There is one observation/case/mode, with category/order coupling, fresh backend
sessions, an instrumentation wrapper and a new clone. No statistical equivalence,
full application latency reproduction or new G6 PASS is claimed. EXPLAIN reports
cardinality but does not retain returned IDs/text/scores: it is not a full semantic
equivalence test for a future rewrite. In particular these ES keyword legs are
empty; future regression must exercise positive lexical matches and tied ranks.
No current runtime correctness failure or C1 overhead measurement is inferred.

## Verification and retention

All20cases resolved PASS, controller exit0, no errors/unresolved/retry or
cleanup failure. analyze_results.py independently decodes each raw output and
checks markers, hashes, role/tenant/read-only/settings, forced-mode counters,
plan predicates/loops and unchanged P3/schema/business/settings. This is parent
verification, not a distinct-review claim. All500protected source/test/global-env
files remain unchanged; no pytest was needed or run. Only the new cluster was
stopped, with all data/container/markers retained and no resume permitted.
Historical source PG identity/running state and prior stopped environments are
preserved. No source/P5/existing-harness/model/threshold/accounting/global-env/
existing-schema/grant/host-policy change, G9, paid campaign, Notion or commits.
The only schema/role materialization was the approved fresh-clone bootstrap.
P2 audit empty/absent, external/provider calls0, apprequests0, USD0.

## Proposed next action, not implemented

remediation-proposal.md targets only computing the same lexical tsquery once
per statement, without forcing custom in runtime. It requires independent
review and explicit authorization before changing app/core/providers/pgvector_store.py.
Semantic equivalence including positive keyword/RRF ties/RLS must be demonstrated
under real PostgreSQL and both modes. No runtime fix, new image, another A/A,
formal G6 or paid admission follows automatically. Global In Progress / Implement /
DECISION_FREEZE_PASS is unchanged.
