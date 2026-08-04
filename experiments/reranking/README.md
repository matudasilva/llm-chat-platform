# ORQ-22 reranking benchmark dataset

This directory contains the isolated reranking experiment. It is not imported by the application.

## Ground-truth construction

`ground_truth.jsonl` contains exactly 60 queries: 30 English/Spanish pairs over 30 independently
selected repository topics. Each row declares the expected source document(s) and graded relevance
(`2` primary, `1` supporting) before retrieval runs. The registry is not derived from
`PgVectorStore.hybrid_search`, so candidate `recall@30` can be lower than 1.0.

Excluded content follows ADR-006: neither `docs/private/` nor `.framework/` may appear in the
registry or candidate text. Candidate relevance is assigned only by matching retrieved source paths
to the pre-declared judgments. Relevance `>= 1` is binary-relevant for MRR@10 and HitRate@5; the
0/1/2 grades are used directly for NDCG@10.

The stability subsample is permanently the first 20 rows in dataset order. Because languages
alternate, that subsample contains 10 English and 10 Spanish queries.

## Reproduction

1. Provision the ORQ-21 pgvector schema and ingest the repository corpus for tenant `acme` in plain
   mode using `app.scripts.ingest_corpus`.
2. Set `DATABASE_URL_APP` and `OPENAI_API_KEY` in `.env`.
3. Run `python -m experiments.reranking.build_dataset` in the dev environment.
4. Confirm 60 rows and 30 candidates per row, then compute `sha256sum dataset.jsonl`.

## Frozen hashes and sign-off

- `ground_truth.jsonl`: `700c30eb58b98ef8b6998c3c4b414682ec4edc3dd7d129f8899c20fe02f23757`.
- `dataset.jsonl`: `a5a52e4e6484652edecfa871b048d646da2db2b20c51c6d17157cd23f444bdcb`.
- Operator sample: every fifth row (`q001`, `q006`, ..., `q056`), 12/60 = 20%; approved by the
  operator on 2026-08-04 for the frozen dataset hash above.

Candidate-generation evidence: 60 rows, 30 candidates per row, 1,800 candidates total, 30 English
and 30 Spanish queries, no excluded candidate source paths, mean document `recall@30` 0.8417,
minimum 0.0, and 17 queries below 1.0.

The files were committed in `316e424`; the operator approved the 12-row sample on 2026-08-04.
The benchmark-arm gate is open.
