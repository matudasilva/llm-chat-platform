# ORQ-26 retrieval evaluation harness

Answers one question with pre-registered evidence: **is the retriever the problem?**

Measures `PgVectorStore.hybrid_search` directly — not `RetrievalPipeline` — so a run costs one
embedding call per query, makes zero LLM and zero reranker calls, and is reproducible. See
`docs/adr/009-rag-evaluation-harness.md` for why, and for the four alternatives that were discarded.

This directory is not imported by the application. It imports `app.*` in one direction only.

## Contents

| File | Role |
|---|---|
| `build_golden_set.py` | Derives the golden set from ORQ-22's ground truth. Pure file transform: no database, no network. |
| `golden_set.jsonl` | 60 rows — 30 bilingual pairs, frozen. |
| `golden_set.sha256` | The freeze. The runner refuses to execute on mismatch. |
| `registration.json` | The pre-registered contract: metric definitions, `k` values, decision rule, pinned corpus commit, approval fields. |

## The golden set

Derived from `experiments/reranking/ground_truth.jsonl`, which is consumed **read-only** — ORQ-22's
published benchmark evidence stays byte-identical. The labels were declared before retrieval ran
(`build_dataset.py:23` reads them ahead of `hybrid_search`), which is what makes them valid for
measuring recall.

`build_golden_set.py` asserts, rather than assumes, every property the metrics depend on: 60 rows,
30 `en`/`es` pairs, both halves of a pair judged identically, distinct query texts, grades in
`{1, 2}`, no duplicate `source_path` per query, and no judgment naming an ingestion-excluded root.
It refuses to write on any violation, because the fix would otherwise be to edit another ORQ's
frozen file.

Note that grade `0` is implicit for unjudged paths and never appears in the data. Since the
registered relevance rule is `>= 1`, every judgment counts as relevant and the graded scale is
unused by the metrics registered here — it is carried for future graded metrics. Each query has one
or two relevant documents, so **per-query recall is coarse** (0, 0.5 or 1); the aggregates carry the
signal.

## Pre-registration

`registration.json` is the record, not the ORQ spec — `.gitignore:64` excludes `.framework/orqs/`.

A content hash alone would prove only which file produced a run, not that it predated one. So the
runner refuses to execute unless `registration.json` is committed and unmodified in the worktree and
both decision thresholds are non-null; every `runs` row records the file's SHA-256 and the commit
that introduced it; and runs under every registration hash are reported, never only the last.

The decision thresholds ship as `null` **by design**. A threshold chosen after seeing the numbers
registers nothing.

## The corpus is pinned

Ingestion is pinned to the branch merge-base recorded in `registration.json`, with ORQ-26's Task 0
code fix applied.

This ORQ contaminates the corpus it measures in both directions: it edits a labelled document —
`app/core/providers/pgvector_store.py`, judged grade 2 by one query pair — in the very terms of the
query that judges it, and `docs/adr/009` is itself ingested as an unlabelled document competing for
top-k against the labelled ones. Pinning removes both effects by construction, rather than relying
on an author to avoid words that happen to match a query they can read.

The metric therefore describes the corpus at that commit, not at `HEAD`. That is the intended trade.

## Reproduction

1. Check out the pinned commit from `registration.json` into a worktree, and ingest the corpus for
   the registered tenant in `plain` mode via `app.scripts.ingest_corpus`.
2. Set `DATABASE_URL_APP`, `OPENAI_API_KEY`, and the evaluation store DSN in `.env`.
3. Verify the freeze: `python -m experiments.evaluation.build_golden_set --check`.
4. Run the harness and record the run id it prints.

Regenerating the golden set is `python -m experiments.evaluation.build_golden_set` — which rewrites
`golden_set.sha256`, and so requires a new registration commit before anything may be run against it.
