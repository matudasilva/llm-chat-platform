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
| `golden_set.jsonl` | 60 rows — 30 bilingual pairs, frozen. |
| `golden_set.sha256` | The freeze. Verified today by `build_golden_set.py --check` and by the hermetic suite; the specified runner will also verify it at run time. |
| `registration.json` | The **draft** registration: metric definitions, `k` values, decision rule, pinned corpus commit, approval fields. Not yet an enforced pre-registration — see below. |

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
runner is *specified* to refuse execution unless `registration.json` is committed and unmodified in
the worktree and both decision thresholds are non-null; to record the file's SHA-256 and the commit
that introduced it in every `runs` row; and to report runs under every registration hash, never only
the last.

> **Not enforced yet.** `run_evaluation.py` is Task 5 and does not exist. The only control in force
> today is the golden-set checksum. Until the runner exists and is tested against dirty,
> uncommitted, unsigned, checksum-mutated and null-threshold registrations, this is a draft
> registration with stated future controls — not an enforced pre-registration, and not something
> another ORQ may inherit as precedent. `registration.json` says the same in `enforcement_status`.

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

Runs against this pin are **contamination-controlled baseline** runs: comparable to each other and
to nothing else. Any run meant to say something about production relevance must re-pin to a reviewed
commit, recording that commit, the ingestion configuration, document and chunk counts and the
golden-set hash, and re-running the leakage checks. **ORQ-27 and ORQ-28 do not inherit this pin by
default** — inheriting it silently would turn a one-time control into a permanently stale baseline
cited as current evidence.

## What can be run today

```
python -m experiments.evaluation.build_golden_set --check   # verify the freeze
python -m experiments.evaluation.build_golden_set           # regenerate it
```

Regenerating rewrites `golden_set.sha256` and therefore requires a new registration commit before
anything may be run against it.

**There is no harness to run yet.** `run_evaluation.py` is Task 5. Until it exists there is no
reproduction procedure to follow, and no run — baseline or otherwise — may be described as
reproducible or verified: nothing yet proves the corpus in a database was ingested from the pinned
commit with the registered configuration. The runner must write and validate that manifest.

When it exists, a run will additionally need: the pinned commit checked out into a worktree and
ingested for the registered tenant in `plain` mode; `DATABASE_URL_APP`, `OPENAI_API_KEY` and the
evaluation store DSN set; and non-null thresholds plus a signed approval in `registration.json`.
