# Minimal lexical SQL remediation

2026-11-10. **IMPLEMENTED_AWAITING_INDEPENDENT_PATCH_REVIEW**.
This is a source-level SQL remediation, not a new image, A/A calibration, G6
measurement or paid campaign. Preserve `CONTROLLED_G6_FAIL`,
`BLOCKED_CONTROLLED_G6_FAIL` and `In Progress / Implement / DECISION_FREEZE_PASS`.

## Authorized surface and result

Only `app/core/providers/pgvector_store.py` and the new
`tests/core/test_pgvector_query_equivalence.py` are technical changes. The host
adapter was changed only after isolated equivalence and plan validation. Its
bytes equal the proven candidate module (SHA-256
`81a41cba1227be5bceff0b34051b7f976b6a4db65a6853a51616935ff6b8b9b3`).
The entire non-SQL AST is unchanged. All five orders/tiebreakers, three top-k
limits, English text-search configuration, RRF 60, arguments/results and RLS
remain intact. Runtime plan cache policy remains `auto`.

The original repeated lexical expression is replaced by a materialized lexical
value reused by the filter and both rank expressions. A count over the unchanged
semantic CTE establishes the execution dependency needed to preserve vector
error precedence. The actual plan proves one semantic producer and one lexical
producer. There is still one retrieval SELECT/roundtrip.

Candidate 1 (a plain one-row CTE) was rejected: a simultaneous invalid vector
dimension and oversized query changed SQLSTATE `22000` into `54000` under
generic execution. Its source, failure XML and rejection record are retained.
Candidate 2 adds only the reviewed semantic dependency; no error was waived.
See both independent design receipts and `validation-attempts.md`.

## Functional proof before host mutation

`candidate-2-regression.xml`: **239 passed, zero failed/errors/skipped**, 78.01 s.
There are 229 new tests plus ten unchanged determinism/RLS tests. The new suite
compares the complete ordered IDs, document IDs, text, nullable metadata and
exact Decimal scores against a self-contained frozen original SQL constant.

Coverage includes positive lexical-only/semantic-only/overlap groups, forced
ID/membership/RRF ties, EN/ES, Unicode/quotes/stopwords/punctuation/empty/NULL
queries; top-k 0/1/2/3/20/NULL; foreign, unknown and absent tenant contexts;
physical empty database; invalid and empty vectors, negative limits, real
tsquery size errors, and simultaneous invalid inputs. Both forced plan modes
are transaction-local on disposable PostgreSQL. Error comparison preserves
SQLSTATE, exception type and complete server-message identity via SHA-256;
timeouts cannot count as successful error equivalence.

The lexical value's dependency consumes the semantic result without filtering
the keyword leg. With this query, an empty semantic result and positive keyword
result cannot coexist for positive top-k: both scan the same RLS-visible chunk
relation, and semantic has no row filter. The seeded positive keyword-only
candidates nevertheless lie outside semantic top-k and retain the exact fused
tie order. `search_vector`/embedding are schema NOT NULL; NULL query/metadata
cases are tested without altering that schema.

Actual SQLAlchemy/asyncpg compilation and EXPLAIN tests prove one retrieval
execute, one lexical producer outside the per-chunk filter/rank, and one
semantic producer consumed by the dependency. The plan guard fails against
the frozen original generic query; the counterexample for candidate 1 also
remains a regression. Host source was then verified byte-identical to candidate
2, without repeating an identical suite or changing tested bytes.

## Bounded request-free mechanism proof

`local-proof-manifest.json` froze **40 EXPLAIN executions and 60 adapter calls**
before these observations, one attempt each, concurrency 1, no automatic retry.
The original diagnostic helper/driver worker were reused unchanged. All 40/40
plans and 60/60 actual adapter calls passed; the ordered driver projections are
identical in each pair. Exact actual bind order remains embedding/top-k/text/RRF,
with inferred vector/bigint/text/bigint types. Both ordinary driver runs choose
five custom and 25 generic executions under `auto`.

| Interval (five cases each) | Original, ms | Candidate, ms |
|---|---:|---:|
| PG EXPLAIN, custom document | 7.580–8.319 | 7.727–7.986 |
| PG EXPLAIN, generic document | 14.169–18.489 | 7.994–8.378 |
| PG EXPLAIN, custom combined | 7.367–8.030 | 7.904–8.069 |
| PG EXPLAIN, generic combined | 23.074–26.940 | 8.212–8.536 |
| Actual adapter, auto document | 11.869–16.113 | 5.127–12.016 |
| Actual adapter, auto combined | 20.281–25.016 | 5.270–8.004 |

All candidate comparison plans show one semantic producer (20 rows/one loop)
and one lexical producer (one row/one loop), with no `plainto_tsquery` in a
per-row filter. Full raw programs/outputs/metadata/plans/results and worker
records are retained. This supports the local SQL mechanism. R=1, shared state,
order/cache effects and instrumentation limit performance interpretation.
The different intervals are not subtracted or treated as equivalent. The
historical A/A gap's cause is not certified and no gate threshold is waived.

## Isolation, identity and preservation

Existing application image `sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707`
was reused with a read-only source overlay; no new image was built. Fresh
PostgreSQL image `sha256:8e5355e9ff399a002fa46148399a1ac22fb3e9b2d390f857296e6da6b5559ba1`,
network none/no ports, retained P3 (124 documents/2,146 chunks), schema, locale,
roles and settings. Retrieval uses real `rag_app`, RLS and read-only transactions;
owner access only bootstraps/seeds/cleans fresh disposable fixtures. Separate
physical-empty database remains empty. Tests add no production data/schema.

Pre/postflight corpus fingerprint/content, schema, counts and ordinary settings
match. The fresh container is stopped; data/markers remain, no resume. Source
PostgreSQL was not restarted or mutated. Of 500 preexisting protected files,
499 are unchanged and the sole modified one is the authorized adapter. The
new test is additional. Existing unrelated user changes remain untouched.

No API, LLM, embedding, rerank, AWS/OpenAI/GCP service, external egress or paid
operation was executed. P2 audit logs are empty/absent; isolated containers
have no external route. External spend **USD 0**. No P5, model, threshold,
accounting, dependency, schema/grant, global `.env`, retry/fallback, provider
contract, `/chat`, SSE, persistence or telemetry change. No G9/Notion/commit.

Exact commands are in `validation-commands.json`; immutable local execution
commands are also retained per driver directory. The final independent patch
review must verify this source and evidence before source-level acceptance.
Any new image pin, A/A, formal G6 or paid execution requires its own approval;
the current candidate image still contains the unmodified original SQL.
