# ORQ-26 retrieval evaluation harness

Answers one question: **under a frozen configuration, does the deterministic candidate generator
retrieve the labelled documents?**

Measures `PgVectorStore.hybrid_search` directly — not `RetrievalPipeline` — so a run costs one
embedding call per query, makes zero LLM and zero reranker calls, and is deterministic given a fixed
corpus. See `docs/adr/009-rag-evaluation-harness.md` for why, and for the five alternatives that were
discarded.

**What this does not tell you.** Production retrieval also rewrites the query and reranks. A good
score here does **not** clear the production retrieval path, and a poor one does not by itself
indict it. This is a candidate-generator baseline; claims about production retrieval need the
pipeline evaluation, which is ORQ-27's.

This directory is not imported by the application. It imports `app.*` in one direction only.

## Contents

| File | Role |
|---|---|
| `build_golden_set.py` | Derives the golden set from ORQ-22's ground truth. Pure file transform: no database, no network. |
| `run_evaluation.py` | The harness. Runs the guards, measures, computes the registered verdict, writes the run. |
| `metrics.py` / `store.py` | Binary-relevance metrics; the MLflow-compatible store. |
| `golden_set.jsonl` | 60 rows — 30 bilingual pairs, frozen. |
| `golden_set.sha256` | The freeze. Verified by `build_golden_set.py --check`, by the hermetic suite, and by the runner at run time. |
| `registration.json` | The signed pre-registration: metric definitions, `k` values, decision rule with thresholds, pinned corpus commit, approval fields. Enforced by the runner. |

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
unused by the metrics registered here.

**These are binary-relevance metrics, not graded ones.** The grade scale must not be cited as
evidence of finer discrimination than the data supports. Each query has one or two relevant
documents, so per-query recall takes only the values 0, 0.5 and 1; the aggregates carry the signal.
A graded metric, or a separate primary-relevance analysis over grade 2 alone, would need its own
registration before being run.

## Pre-registration

`registration.json` is the record, not the ORQ spec — `.gitignore:64` excludes `.framework/orqs/`.

A content hash alone would prove only which file produced a run, not that it predated one. So the
runner refuses execution unless `registration.json` is committed and unmodified in
the worktree and both decision thresholds are non-null; to record the file's SHA-256 and the commit
that introduced it in every `runs` row; and to report runs under every registration hash, never only
the last.

> **Enforced.** `run_evaluation.py` refuses to measure anything unless every guard passes: a
> committed and unmodified `registration.json`, non-null thresholds, a present approval signature, a
> matching golden-set hash, a corpus manifest whose commit equals the pinned one, and no golden-set
> query text in the ingested corpus. Every refusal is exercised by a test that observes it failing.

The thresholds were set and committed **before** the first run: `recall_at_10_floor = 0.65` and
`recall_gap_margin = 0.12`. They are calibrated on `experiments/reranking/dataset.jsonl`, which
predates this ORQ entirely — recomputing these metric definitions over ORQ-22's frozen candidates
gives `recall@10 = 0.7167` and a gap of `0.0750`. Calibrating on a prior dataset is not previewing
the run. A threshold chosen after seeing the numbers would register nothing, which is why the runner
refuses to execute while either is null.

## The corpus is pinned

Ingestion is pinned to the branch merge-base recorded in `registration.json`, with ORQ-26's Task 0
code fix applied.

This ORQ contaminates the corpus it measures in both directions: it edits a labelled document —
`app/core/providers/pgvector_store.py`, judged grade 2 by one query pair — in the very terms of the
query that judges it, and `docs/adr/009` is itself ingested as an unlabelled document competing for
top-k against the labelled ones. Pinning removes both effects by construction, rather than relying
on an author to avoid words that happen to match a query they can read.

The metric therefore describes the corpus at that commit, not at `HEAD`. That is the intended trade.

Runs against this pin are **contamination-controlled baseline** runs: comparable to each other and
to nothing else. Any run meant to say something about production relevance must re-pin to a reviewed
commit, recording that commit, the ingestion configuration, document and chunk counts and the
golden-set hash, and re-running the leakage checks. **ORQ-27 and ORQ-28 do not inherit this pin by
default** — inheriting it silently would turn a one-time control into a permanently stale baseline
cited as current evidence.

## Corpus integrity

Running `pytest` executes `tests/core/test_rag_migration.py`, which performs a schema
downgrade/upgrade cycle that empties `documents` and `chunks`. **After running the full test suite,
re-run `ingest_corpus.py` before calling `run_evaluation.py`.**

The runner detects this and exits with `CorpusStateError` rather than measuring an empty corpus. That
guard exists because the failure already happened once: before it, a wiped corpus produced a silent
run of `0.0` across every metric, which reads like a finding rather than like a broken environment.

## What can be run today

```
python -m experiments.evaluation.build_golden_set --check   # verify the freeze
python -m experiments.evaluation.build_golden_set           # regenerate it
```

Regenerating rewrites `golden_set.sha256` and therefore requires a new registration commit before
anything may be run against it.

Running the harness needs the pinned corpus ingested first. Ingest from a worktree at the pinned
commit, so this ORQ's own text never enters the corpus it measures:

```
git worktree add /tmp/orq26-corpus <pinned_commit>
python -m app.scripts.ingest_corpus --tenant-id acme --repo-root /tmp/orq26-corpus
```

Run from the main tree, not the worktree: the corpus content comes from the pinned commit, the code
running the search comes from `HEAD`, and the manifest belongs to the main tree. Then:

```
python -m experiments.evaluation.run_evaluation --dry-run   # guards + metrics, no store write
python -m experiments.evaluation.run_evaluation             # records a run
```

Needs `DATABASE_URL_APP`, `OPENAI_API_KEY` and `EVALUATION_STORE_URL`. A repeated run inserts a
second row rather than replacing the first — see ADR-009 decision 3 for why that is an audit
property, not a storage detail.

## Running the hermetic test suite

The evaluation test suites need three DSNs, none of which is `EVALUATION_STORE_URL` above:

| Variable | Role | Used for |
|---|---|---|
| `RAG_TEST_DATABASE_URL` | privileged (superuser) | seeding fixtures, teardown, inspection |
| `RAG_TEST_DATABASE_URL_APP` | `rag_app` | the isolation assertion (that `rag_app` cannot read the evaluation schema) |
| `EVALUATION_TEST_DATABASE_URL` | `rag_evaluation` | the store role itself — `test_evaluation_store.py` and `test_settings_evaluation_store.py` connect **as this role, not as the superuser** |

Pointing `EVALUATION_TEST_DATABASE_URL` at the superuser role does not skip the test — it fails it:
`ensure_schema` refuses a superuser outright (ADR-009 decision 3), so the store suite would report
failures that look like a broken guard rather than a wrong DSN. Provision `rag_evaluation` with the
`CREATE ROLE` statement in ADR-009 decision 3 before running this suite locally.
