# ADR-009: RAG Evaluation Harness — Instrument, Store, and Pre-registration

**Date:** 2026-08-08
**Status:** Proposed
**ORQ reference:** ORQ-26
**Superseded by / Supersedes:** —

---

## Context

ORQ-21 through ORQ-25 built a RAG path — corpus and hybrid retrieval, a reranker benchmark, a
retrieval pipeline, a reranker cascade, and augmented chat generation — without ever measuring
whether retrieval finds the right documents. Every improvement so far was argued from design, not
from evidence.

ORQ-26 answers one question: **under a frozen configuration, does the deterministic candidate
generator retrieve the labelled documents?**

That wording is deliberately narrower than the "is the retriever the problem?" framing earlier drafts
of this ADR used, and the narrowing is not cosmetic. What is measured is `hybrid_search` alone.
Production retrieval also rewrites the query and reranks, so **a good score here does not clear the
production retrieval path**, and a poor one does not by itself indict it. Any claim about production
retrieval needs the pipeline evaluation, which belongs to ORQ-27. Calling this a verdict on "the
retriever" would be an overclaim, and the decision rule below must be read as a verdict on the
candidate generator only.

The scope is narrow on purpose.
The roadmap's original evaluation item bundled retriever metrics, LLM-as-judge answer quality, and
a contextual-retrieval A/B; the operator split it on 2026-08-07 into ORQ-26, ORQ-27 and ORQ-28
after Early Design Review found the combined scope violated this project's own precedent of
narrowing ORQs.

Four constraints shaped the design, each verified against the tree rather than the documentation:

- `RetrievalPipeline.retrieve()` calls `_rewrite` → `provider.generate` for **every** query
  (`retrieval_pipeline.py:94,153-160`), then a reranker cascade whose AWS fallback quota is
  2 req/min (ADR-007). A 60-query run through the pipeline is 60 live LLM calls plus 60 rerank
  calls, and two runs of the same frozen set are free to disagree.
- ORQ-21's golden set exists only as a prose table in ADR-006 §Retrieval golden set. Nothing
  machine-readable existed to measure against.
- `experiments/reranking/ground_truth.jsonl` already holds 30 bilingual query pairs whose judgments
  were declared *before* retrieval ran (`build_dataset.py:23` reads them ahead of `hybrid_search`),
  which makes them valid labels for retriever recall.
- `rag_app` is deliberately non-owner and non-superuser (ADR-006 §2), and
  `scripts/postgres-init/10-rag-app-role.sh` only runs against a freshly initialised data
  directory.

---

## Decision

### 1. Measure the deterministic candidate generator, not the pipeline

The harness calls `PgVectorStore.hybrid_search(query_text, query_embedding, top_k=…)` directly,
embedding each query through the existing `build_embedding_provider(cfg)` at its own call site. No
production signature changes.

The value of this ORQ is a measurement that can be repeated and compared. Measuring through `RetrievalPipeline` would make the one
deliverable whose worth is a repeatable number depend on two managed services per query, against a
documented quota, with a `top_n` default of 5 that no "@10" measurement could honestly use. Rewrite
and rerank stay unmeasured until ORQ-27, which needs call budgeting and judge-stability machinery
anyway.

The trade is deliberate: a repeatable answer about the candidate generator, rather than an
irreproducible answer about everything. Two consecutive runs against the pinned corpus produced
identical metrics at every granularity, which is the property the instrument was chosen for.

### 2. Fix `hybrid_search`'s ordering first — it was not deterministic

Design review found, at round 4, that the instrument chosen in decision 1 did not have the property
it was chosen for. Reciprocal Rank Fusion produces exact score ties **by construction**: a chunk
found only by the semantic leg at rank *r* scores `1.0/(60+r)`, identical to a chunk found only by
the keyword leg at the same rank. No `ORDER BY` in the query carried a tiebreaker, so the plan
decided the order.

This was never only a measurement problem. Two identical `/chat` requests could already cite
different sources, with no change to the corpus, whenever an autovacuum or a plan change reordered
tied rows.

The fix adds `id` as the final ordering key to **all five** `ORDER BY` clauses — each CTE has two,
its `row_number()` window and its own `ORDER BY … LIMIT :top_k`. Fixing only the windows, as first
proposed, would leave pool *membership* non-deterministic while making the ranking within it look
stable: the `LIMIT` ordering decides which rows enter the candidate pool at all, and `ts_rank` ties
at the cutoff boundary are the common case.

**This is a ranking policy on the production retrieval path, and is approved here as such — not as
a cosmetic fix.** An earlier draft of this ADR claimed the change "never reorders chunks with
distinct scores". That is false, and the correction matters. `row_number()` assigns the rank that
feeds the RRF score, so ordering tied candidates by `id` decides which of them scores `1/(60+r)` and
which scores `1/(60+r+1)`. Those differing scores can then order differently against a third chunk
whose score was never tied with either. Only the final `ORDER BY score DESC, id` is a pure
tie-break; the four CTE-level keys are not.

What the change does *not* do is introduce a preference among candidates that were not already tied
on cosine distance or `ts_rank`. Both the old and the new order among ties are arbitrary — a v4 UUID
carries no semantic bias, and neither did the query plan. What changed is that the arbitrary order
is now stable. We accept an arbitrary-but-stable ranking of tied candidates over an
arbitrary-and-unstable one, because a retrieval system that returns different sources for identical
requests cannot be measured, and cannot be trusted to cite.

An alternative tiebreaker with semantic meaning — `ordinal`, `document_id`, recency — would express
a preference this project has no evidence for. Choosing one would be a retrieval-quality decision,
which is explicitly out of scope here; `id` is the deliberate refusal to make it.

The regression tests seed corpora that *force* both tie shapes rather than repeating a call and
comparing. That distinction is load-bearing: against the unfixed query, in the recorded environment
and across three consecutive runs, the repeat-and-compare test passed while the tie-forcing tests
failed. This is observed evidence rather than a guarantee — an unfixed query may return id order
under some valid plan — but a determinism test that *can* pass on non-deterministic code is not
evidence, and the repeat-and-compare test demonstrably did.

### 3. Pre-registration establishes precedence, not merely association

`.gitignore:64` excludes `.framework/orqs/`, so the ORQ spec cannot be the public record. The frozen
contract is a tracked `experiments/evaluation/registration.json` carrying the metric definitions,
the `k` values, the decision rule, the golden set's SHA-256, the pinned corpus commit, and
`approved_by` / `approved_at`.

A content hash alone proves only which file produced a run. It does not prevent registering `k=10`,
running, disliking the number, editing, re-running, and reporting only the second set. So the runner:

- refuses to execute unless `registration.json` is committed and unmodified in the worktree, and
  unless both decision thresholds are non-null and the approval is signed;
- refuses to execute unless the instrument itself is committed and unmodified, and records that
  commit as `runner_commit`. Without it a run could name a revision that does not describe the code
  that produced it. "The instrument" is every file that shapes a measurement, not just the runner:
  the runner, the metrics, the store, `pgvector_store.py`, `retrieval_factory.py` (selects the
  embedding provider), `openai_embedding_provider.py` and `settings.py` (the model, dimensions and
  request payload behind every vector), and `corpus_fingerprint.py` (the live content check's
  digest). The canonical list is `_INSTRUMENT_PATHS` in `run_evaluation.py` — enumerated here for
  readability, not duplicated as a second source of truth to drift from it;
- records the file's SHA-256 **and** the commit that introduced it in every `runs` row;
- requires a new commit for re-registration, and reports runs under every registration hash — never
  only the last.

**A run never overwrites a run.** Repeating the harness against the same golden set, the same
registration and the same corpus inserts a *second* row in `runs` with its own `run_id` and
timestamp; it does not update the first. Nothing in the schema can collapse them — `run_id` is the
primary key and no uniqueness constraint spans the registration hash.

This is an audit property, not a storage detail. A store that overwrote would make "we ran it again
and it looked better" indistinguishable from "it always looked like that", which is precisely the
manipulation the pre-registration exists to prevent. It also makes the harness's own stability
observable: two rows carrying identical metrics are evidence of determinism, and a pair that
disagrees is evidence something changed underneath — either of which is lost if the second write
replaces the first.

**Enforcement status: enforced.** `experiments/evaluation/run_evaluation.py` implements every guard
above and refuses to measure anything until they pass — a modified or uncommitted
`registration.json`, a null threshold, a missing approval signature, a golden-set hash mismatch, a
missing corpus manifest, a manifest whose commit differs from the pinned one, or any golden-set query
found in the ingested corpus. Each refusal is exercised by a test that observes it failing, because a
guard never seen refusing is not a guard. `registration.json` carries the same statement in
`enforcement_status`.

Earlier revisions of this ADR said the opposite, correctly: until Tasks 4-6 landed the file was a
draft registration with stated future controls, and could not be inherited as precedent.

### 4. Pin the measured corpus to the branch merge-base

ORQ-26 contaminates the corpus it measures, in both directions. It edits
`app/core/providers/pgvector_store.py` — a labelled document, judged grade 2 by one query pair and
grade 1 by another — adding a comment that raises that document's term frequency in precisely the
terms of the query that judges it. And this ADR is itself ingested under `docs/`, where an
unlabelled document topically adjacent to labelled queries competes for top-k against the documents
that carry the labels.

Ingestion is therefore pinned to the branch merge-base, with the ordering fix of decision 2 applied. It
changes ordering, not content, so it belongs in the measurement; this ORQ's prose does not. Pinning
removes both effects by construction, rather than relying on the author of a document to choose
words that do not happen to match a query they can read.

The cost is that the metric describes a corpus that is not current `HEAD`, and the pinned commit is
recorded in every run.

**A pin without a re-pinning policy is a stale baseline waiting to happen**, so the policy is set
here rather than deferred. Runs of this pinned corpus are *contamination-controlled baseline* runs:
comparable to each other and to nothing else, which is their entire purpose. Any run intended to say
something about production relevance must re-pin to a reviewed commit, recording that commit, the
ingestion configuration, document and chunk counts, and the golden-set hash, and re-running the
leakage and contamination checks against the new corpus.

**ORQ-27 and ORQ-28 do not inherit this pin by default.** Inheriting it silently would convert a
one-time contamination control into a permanently stale baseline presented as current evidence — the
corpus drifts further from production with every ORQ, while the number keeps being cited as reusable.
`app.scripts.ingest_corpus` writes a corpus manifest recording the ingested revision, and the runner
refuses to execute without one or when its commit differs from the pinned one. The manifest is an
honest declaration of what the ingesting process saw, not a proof: a later hand-edit of the database
would not invalidate it. Proving the correspondence would mean recomputing every `content_hash` from
the pinned worktree at run time.

The registration also pins `ingestion_mode` (`"plain"`), and the manifest records the corpus's actual
`indexing_mode` alongside `content_fingerprint`. The two are checked separately because they defend
against different things: `content_fingerprint` is a digest over `(source_path, content_hash)` and
is blind to how a chunk was embedded, so a corpus rebuilt with `--contextualize` over the same files
would share the identical fingerprint while every chunk's embedding input differs from the registered
baseline. The runner refuses if the manifest's `indexing_mode` does not match the registration's, and
separately refuses (live, against the database) if the corpus no longer agrees with what the manifest
declared — closing both the "wrong mode was ever ingested" and the "corpus was re-ingested in a
different mode after the manifest was written" cases (round 4 of tranche 2 review).

### 5. The store is a separate schema, a provisioned role, and outside the Alembic chain

The harness owns an `evaluation` schema through idempotent DDL, never an Alembic revision, with an
MLflow-compatible shape — `runs`, `metrics`, `params`, `tags`. An experiment must not be able to
introduce a migration into the chain that serves the product.

`rag_app` cannot create a schema by design, and the existing init script only runs on a fresh data
directory, so `scripts/postgres-init/20-evaluation-role.sh` covers local setup from scratch. For an
existing or managed database — the common case in staging, and the case the init script cannot
reach — the equivalent must be run once by hand as a privileged user:

```sql
CREATE ROLE rag_evaluation LOGIN PASSWORD '<secret>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT CONNECT ON DATABASE <db> TO rag_evaluation;
-- The harness creates the `evaluation` schema itself on first run.
GRANT CREATE  ON DATABASE <db> TO rag_evaluation;
-- Nothing on `public`, where the application's tables live. Explicit because
-- the defaults on `public` have changed across Postgres major versions.
REVOKE ALL ON SCHEMA public FROM rag_evaluation;
```

`rag_app` needs no counterpart statement: the schema does not exist at provisioning time and the
harness creates it as `rag_evaluation`, so `rag_app` never acquires anything on it. Verified —
`rag_app` reading a table in a schema owned by `rag_evaluation` fails with `permission denied for
schema`, and the store role reports `rolsuper = false`.

The store DSN is a
setting in `app/core/settings.py`, following the precedent ORQ-22's `reranking_benchmark_*` settings
set, and its validator rejects a DSN equal to `database_url` — the superuser — because that is the
failure this would otherwise drift into. Rejecting `database_url_app` would guard the wrong
direction: that role is under-privileged, not over-privileged. `rag_app` receives no grant on
`evaluation`.

That string comparison is an **ergonomic early error, not the control**: an equivalent DSN differing
in a query parameter, host alias, password encoding or URL form passes it. The authoritative check is
at connection time — `EvaluationStore.ensure_schema` queries `pg_roles.rolsuper` for the actually
connected role and raises before issuing any DDL. A DSN string can lie by being merely equivalent;
`rolsuper` cannot.

### 6. The harness lives entirely under `experiments/`

`Dockerfile:26` copies `app/` wholesale into the production image, so a runner under `app/scripts/`
importing `experiments/` would ship a broken module. Worse, ingestion walks `app/**.py`
(`ingest_corpus.py:48-50`), so a runner placed there would be ingested into the corpus it measures.
Runner, store and build script live in `experiments/evaluation/`, importing `app.*` in one direction
only.

### 7. Declared deviations

- **OpenTelemetry span emission**, which the roadmap assigned to ORQ-26, moves to ORQ-29 so
  instrumentation is designed once together with its backend.
- **The instrument is narrower than the roadmap wording** — the candidate generator, not the full
  pipeline (decision 1).
- **The roadmap states ORQ-26 carries pushing the frontend commit `f79f920`.** With the frontend out
  of scope that belongs to ORQ-25's closure record; the same change amends the roadmap to say so.
- **Embeddings stay on OpenAI for this ORQ**, despite the recorded intent to move them off. ORQ-22's
  ceiling was measured with the same embedding call; changing the model here would make the run
  measure something else. The swap is deferred and is itself a candidate for a later run of this
  harness — which is the point of building it.

`mission.md` §Excluded defers MLflow. This store is MLflow-*compatible*, adds no MLflow dependency,
and so respects the exclusion rather than deviating from it.

---

## Consequences

### Positivas

- A zero-LLM-cost measurement of candidate-generator quality that later ORQs re-run to judge a
  change, rather than arguing it from design.
- A production bug fixed: `/chat` no longer returns unstable source attributions for identical
  requests.
- A pre-registration discipline enforced by the runner rather than by convention. It refuses a
  modified registration or instrument, a null threshold, an unsigned approval, a mutated golden set,
  a missing or mismatched corpus manifest, a corpus that does not match the counts the manifest
  declares, and any golden-set query found in the corpus.
- Evaluation data cannot reach business tables: separate schema, separate role, no migration.

### Negativas / Trade-offs

- The measurement excludes rewrite and rerank, so a good retriever score does not clear the pipeline.
- The pinned corpus diverges from `HEAD` as the repository moves; the number describes the corpus at
  a commit, not the deployed one.
- Labels are binary in practice — every judged path is grade 1 or 2, so `>= 1` admits all of them —
  and each query has one or two relevant documents, which makes per-query recall coarse (0, 0.5 or
  1). Aggregates over 60 queries carry the signal; single-query values should not be over-read.
- A second Postgres role and schema is one more thing to provision in every environment.
- The tiebreaker is a ranking policy on the production path, not a free fix. Because CTE ranks feed
  RRF scores, it can change the relative order of chunks whose final scores differ, and retrieval
  evidence captured before it may not reproduce row-for-row. It cannot be argued to *improve*
  ranking either — the claim is only that an arbitrary-but-stable order beats an
  arbitrary-and-unstable one.
- The metrics are binary-relevance, and the store is fixed to one schema; both are narrower surfaces
  than a general evaluation framework would offer, deliberately.
- The test suite and the measured corpus are mutually destructive. `tests/core/test_rag_migration.py`
  downgrades the schema, which empties `documents` and `chunks`, so running the full suite requires
  re-ingesting before evaluating. That test belongs to ORQ-21 and is not changed here; the runner's
  corpus guard turns the collision into a refusal instead of a silent run of zeros, which is what it
  produced before the guard existed.

---

## Alternativas Consideradas

### Alternativa A: Measure through `RetrievalPipeline`

Closest to what production runs, and the roadmap's literal wording. Discarded: 60 live LLM rewrites
and 60 rerank calls per run against a 2 req/min fallback quota, non-reproducible by construction,
and a `top_n` default of 5 that cannot honestly produce an @10 metric. ORQ-27 takes it up with the
machinery that problem needs.

### Alternativa B: Accept non-determinism and report variance instead

Run the set repeatedly and report a distribution rather than a value. Discarded: it would have
normalised a production defect as a measurement property, and left `/chat` citing unstable sources.
The variance was not inherent to retrieval — it was a missing `ORDER BY` key.

### Alternativa C: Store results in the application database under Alembic

Fewer moving parts, one DSN, one migration chain. Discarded: it gives an experiment a revision in
the chain that serves the product, and a write path into the database holding business data.

### Alternativa D: Measure the corpus at `HEAD` and flag the affected queries

Simpler to operate; `registration.json` would mark the four affected query ids as confounded.
Discarded: it leaves four pairs permanently asterisked, and it does not address the second-order
effect of this ADR competing as an unlabelled document. Pinning removes both.

### Alternativa E: Reuse ORQ-21's golden set from ADR-006

It is the project's declared golden set. Discarded: it exists only as prose, it is 10 queries rather
than 30 pairs, it is monolingual, and ADR-006 embeds all ten prompts verbatim and is itself
ingested — so each prompt matches its own expected document lexically. ORQ-22's set has none of
those defects and its labels predate retrieval.

---

## Evidencia

- Commit `178622e` — `fix(retrieval): make hybrid_search ordering deterministic` (decision 2)
- Test: `tests/core/test_pgvector_store_determinism.py` — both tie shapes forced; observed red
  against the pre-fix query across three consecutive runs in the recorded environment, and green
  after. Observed evidence, not a guarantee: see decision 2
- Source labels: `experiments/reranking/ground_truth.jsonl`, consumed read-only; ORQ-22's
  `dataset.sha256` recomputes unchanged
- Derived contract: `experiments/evaluation/golden_set.jsonl` +
  `experiments/evaluation/registration.json`
- Query rewrite per query: `app/core/domain/retrieval_pipeline.py:94,153-160`
- Fusion and the `LIMIT`-inside-CTE structure: `app/core/providers/pgvector_store.py:86-101`
- Prior decisions: `docs/adr/006-rag-corpus-embeddings-and-rls.md` §1, §2, §Retrieval golden set;
  `docs/adr/007-reranker-availability-cascade.md`
