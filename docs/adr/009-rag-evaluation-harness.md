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

ORQ-26 answers one question: **is the retriever the problem?** That framing is narrow on purpose.
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

The value of this ORQ is reproducibility. Measuring through `RetrievalPipeline` would make the one
deliverable whose worth is a repeatable number depend on two managed services per query, against a
documented quota, with a `top_n` default of 5 that no "@10" measurement could honestly use. Rewrite
and rerank stay unmeasured until ORQ-27, which needs call budgeting and judge-stability machinery
anyway.

The trade is deliberate: a reproducible answer about the retriever now, rather than an
irreproducible answer about everything.

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
at the cutoff boundary are the common case. `id` is a random UUID — arbitrary as a preference but
stable — and never reorders chunks with distinct scores, so ranking quality is unchanged by
construction.

The regression tests seed corpora that *force* both tie shapes rather than repeating a call and
comparing. That distinction is load-bearing: against the unfixed query, the repeat-and-compare test
passed while both tie-forcing tests failed. A determinism test that can pass on non-deterministic
code is not evidence.

### 3. Pre-registration establishes precedence, not merely association

`.gitignore:64` excludes `.framework/orqs/`, so the ORQ spec cannot be the public record. The frozen
contract is a tracked `experiments/evaluation/registration.json` carrying the metric definitions,
the `k` values, the decision rule, the golden set's SHA-256, the pinned corpus commit, and
`approved_by` / `approved_at`.

A content hash alone proves only which file produced a run. It does not prevent registering `k=10`,
running, disliking the number, editing, re-running, and reporting only the second set. So:

- the runner refuses to execute unless `registration.json` is committed and unmodified in the
  worktree, and unless both decision thresholds are non-null;
- every `runs` row records the file's SHA-256 **and** the commit that introduced it;
- re-registration requires a new commit, and runs under every registration hash are reported —
  never only the last.

### 4. Pin the measured corpus to the branch merge-base

ORQ-26 contaminates the corpus it measures, in both directions. It edits
`app/core/providers/pgvector_store.py` — a labelled document, judged grade 2 by one query pair and
grade 1 by another — adding a comment that raises that document's term frequency in precisely the
terms of the query that judges it. And this ADR is itself ingested under `docs/`, where an
unlabelled document topically adjacent to labelled queries competes for top-k against the documents
that carry the labels.

Ingestion is therefore pinned to the branch merge-base, with the Task 0 code fix applied. The fix
changes ordering, not content, so it belongs in the measurement; this ORQ's prose does not. Pinning
removes both effects by construction, rather than relying on the author of a document to choose
words that do not happen to match a query they can read.

The cost is that the metric describes a corpus that is not current `HEAD`. That is the right price
for a pre-registered experiment about the retriever, and the pinned commit is recorded in every run.

### 5. The store is a separate schema, a provisioned role, and outside the Alembic chain

The harness owns an `evaluation` schema through idempotent DDL, never an Alembic revision, with an
MLflow-compatible shape — `runs`, `metrics`, `params`, `tags`. An experiment must not be able to
introduce a migration into the chain that serves the product.

`rag_app` cannot create a schema by design, and the existing init script only runs on a fresh data
directory, so a second `scripts/postgres-init/` script covers local setup while this ADR documents
the manual `CREATE ROLE` / `GRANT` path for existing and managed databases. The store DSN is a
setting in `app/core/settings.py`, following the precedent ORQ-22's `reranking_benchmark_*` settings
set, and its validator rejects a DSN equal to `database_url` — the superuser — because that is the
failure this would otherwise drift into. Rejecting `database_url_app` would guard the wrong
direction: that role is under-privileged, not over-privileged. `rag_app` receives no grant on
`evaluation`.

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

- A repeatable, zero-LLM-cost measurement of retrieval quality that later ORQs can re-run to judge a
  change, rather than arguing it from design.
- A production bug fixed: `/chat` no longer returns unstable source attributions for identical
  requests.
- Pre-registration discipline, with enforcement in the runner rather than in a convention, inherited
  by ORQ-27 and ORQ-28.
- Evaluation data cannot reach business tables: separate schema, separate role, no migration.

### Negativas / Trade-offs

- The measurement excludes rewrite and rerank, so a good retriever score does not clear the pipeline.
- The pinned corpus diverges from `HEAD` as the repository moves; the number describes the corpus at
  a commit, not the deployed one.
- Labels are binary in practice — every judged path is grade 1 or 2, so `>= 1` admits all of them —
  and each query has one or two relevant documents, which makes per-query recall coarse (0, 0.5 or
  1). Aggregates over 60 queries carry the signal; single-query values should not be over-read.
- A second Postgres role and schema is one more thing to provision in every environment.
- The tiebreaker changes the observed order of tied results. It cannot degrade ranking, but evidence
  captured before it may not reproduce row-for-row among tied rows.

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
- Test: `tests/core/test_pgvector_store_determinism.py` — both tie shapes forced; shown red against
  the pre-fix query and green after
- Source labels: `experiments/reranking/ground_truth.jsonl`, consumed read-only; ORQ-22's
  `dataset.sha256` recomputes unchanged
- Derived contract: `experiments/evaluation/golden_set.jsonl` +
  `experiments/evaluation/registration.json`
- Query rewrite per query: `app/core/domain/retrieval_pipeline.py:94,153-160`
- Fusion and the `LIMIT`-inside-CTE structure: `app/core/providers/pgvector_store.py:86-101`
- Prior decisions: `docs/adr/006-rag-corpus-embeddings-and-rls.md` §1, §2, §Retrieval golden set;
  `docs/adr/007-reranker-availability-cascade.md`
