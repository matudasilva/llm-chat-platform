"""Retrieval metrics for ORQ-26, implemented exactly as pre-registered.

Every choice below is fixed by `registration.json` and must not drift from it:

  scored unit      distinct `source_path`, resolved from the retrieved
                   `document_id` by a post-query lookup
  window           top-*k* **chunks**, collapsed to distinct `source_path`
                   *after* truncation — so `k` counts chunks, not documents
  document rank    dense: position in the collapsed list, not the rank of the
                   chunk it first appeared at
  relevance        grade >= 1
  MAP denominator  min(|relevant|, k)

The relevance rule is restated here rather than imported. ORQ-22 applies it at
`app/scripts/run_reranking_benchmark.py:297,301` without exporting a constant,
and `app/` -> `experiments/` imports are forbidden (ADR-009 decision 6), so the
only honest options were to duplicate it with a comment naming its source or to
let the two definitions drift silently.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# Mirrors run_reranking_benchmark.py:297,301. Note that every judgment in the
# golden set is grade 1 or 2 — grade 0 is implicit for unjudged paths and never
# written — so this admits all of them. The threshold is kept explicit anyway,
# because a future graded set would need it and a silently-inlined `True` would
# not survive that change.
_RELEVANCE_THRESHOLD = 1


def is_relevant(grade: int) -> bool:
    return grade >= _RELEVANCE_THRESHOLD


def relevant_paths(judgments: Iterable[dict]) -> set[str]:
    """The relevant `source_path` set for one golden-set row."""
    return {
        judgment["source_path"] for judgment in judgments if is_relevant(judgment["grade"])
    }


def collapse(source_paths: Sequence[str], k: int) -> list[str]:
    """Truncates to the top-*k* chunks, then collapses to distinct documents.

    The order matters and is the registered one. Collapsing *before* truncating
    would make `k` count documents, so `k=10` would reach deeper into the
    ranking whenever a document contributed several chunks — a different
    measurement wearing the same name.
    """
    if k < 0:
        raise ValueError(f"k must be non-negative, got {k}")
    seen: set[str] = set()
    collapsed: list[str] = []
    for source_path in source_paths[:k]:
        if source_path not in seen:
            seen.add(source_path)
            collapsed.append(source_path)
    return collapsed


def recall_at_k(source_paths: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant documents that appear in the top-*k* chunks.

    Undefined without a relevant document, so callers must not pass an empty
    set; the golden set's derivation already guarantees at least one.
    """
    if not relevant:
        raise ValueError("recall is undefined for a query with no relevant documents")
    found = relevant & set(collapse(source_paths, k))
    return len(found) / len(relevant)


def average_precision_at_k(source_paths: Sequence[str], relevant: set[str], k: int) -> float:
    """Average precision over the collapsed document list.

    The denominator is `min(|relevant|, k)`, not the hit count: dividing by hits
    would score a query that found one of two relevant documents identically to
    one that found both, which is precisely the distinction the metric exists to
    make.
    """
    if not relevant:
        raise ValueError("average precision is undefined for a query with no relevant documents")
    hits = 0
    precision_sum = 0.0
    for position, source_path in enumerate(collapse(source_paths, k), start=1):
        if source_path in relevant:
            hits += 1
            precision_sum += hits / position
    return precision_sum / min(len(relevant), k)


def reciprocal_rank_at_k(source_paths: Sequence[str], relevant: set[str], k: int) -> float:
    """Reciprocal of the dense rank of the first relevant document; 0 if none."""
    if not relevant:
        raise ValueError("reciprocal rank is undefined for a query with no relevant documents")
    for position, source_path in enumerate(collapse(source_paths, k), start=1):
        if source_path in relevant:
            return 1.0 / position
    return 0.0


def mean(values: Sequence[float]) -> float:
    """Unweighted mean, as registered. Empty input is a caller error, not 0.0."""
    if not values:
        raise ValueError("cannot take the mean of an empty sequence")
    return sum(values) / len(values)
