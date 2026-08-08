"""ORQ-26 AC4: every registered metric is implemented as registered.

The expected values here are derived by hand from `registration.json`'s
definition table and written out in the comments, so a reviewer can check the
arithmetic without re-deriving the intent. A test that recomputed the metric
with the same code it is testing would assert nothing.
"""

from __future__ import annotations

import pytest

from experiments.evaluation.metrics import (
    average_precision_at_k,
    collapse,
    is_relevant,
    mean,
    recall_at_k,
    reciprocal_rank_at_k,
    relevant_paths,
)

# Chunk-level ranking. `b.md` contributes two chunks and `a.md` three, which is
# what makes collapsing observable rather than incidental.
_RANKING = [
    "a.md",  # chunk rank 1  -> document rank 1
    "a.md",  # chunk rank 2  -> collapsed away
    "b.md",  # chunk rank 3  -> document rank 2
    "c.md",  # chunk rank 4  -> document rank 3
    "a.md",  # chunk rank 5  -> collapsed away
    "d.md",  # chunk rank 6  -> document rank 4
    "b.md",  # chunk rank 7  -> collapsed away
    "e.md",  # chunk rank 8  -> document rank 5
]


def test_collapse_truncates_chunks_before_deduplicating() -> None:
    # Top-4 chunks are a, a, b, c -> three distinct documents. Collapsing first
    # would instead have reached c.md's chunk *and* d.md's, which is the whole
    # reason the registered order is truncate-then-collapse.
    assert collapse(_RANKING, 4) == ["a.md", "b.md", "c.md"]
    assert collapse(_RANKING, 8) == ["a.md", "b.md", "c.md", "d.md", "e.md"]
    assert collapse(_RANKING, 0) == []


def test_collapse_preserves_first_occurrence_order() -> None:
    assert collapse(["z.md", "y.md", "z.md", "x.md"], 4) == ["z.md", "y.md", "x.md"]


def test_collapse_rejects_negative_k() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        collapse(_RANKING, -1)


def test_recall_counts_distinct_documents_not_chunks() -> None:
    # relevant = {a.md, d.md}. Top-4 chunks collapse to [a, b, c]: 1 of 2 found.
    assert recall_at_k(_RANKING, {"a.md", "d.md"}, 4) == 0.5
    # Top-8 chunks reach d.md at document rank 4: 2 of 2.
    assert recall_at_k(_RANKING, {"a.md", "d.md"}, 8) == 1.0
    # a.md appears three times but is one document, so recall cannot exceed 1.
    assert recall_at_k(_RANKING, {"a.md"}, 8) == 1.0


def test_recall_is_zero_when_nothing_relevant_is_retrieved() -> None:
    assert recall_at_k(_RANKING, {"missing.md"}, 8) == 0.0


def test_average_precision_uses_dense_document_ranks() -> None:
    # relevant = {b.md, d.md}, collapsed = [a, b, c, d, e].
    # b.md at document rank 2 -> precision 1/2; d.md at rank 4 -> precision 2/4.
    # Dense ranks matter: b.md's chunk rank was 3 and d.md's was 6, which would
    # have given 1/3 and 2/6 instead.
    # denominator = min(|relevant|, k) = min(2, 8) = 2.
    expected = (1 / 2 + 2 / 4) / 2
    assert average_precision_at_k(_RANKING, {"b.md", "d.md"}, 8) == pytest.approx(expected)


def test_average_precision_denominator_is_min_relevant_k_not_hit_count() -> None:
    # Only a.md is retrieved within the top-4 chunks, but two documents are
    # relevant. Dividing by the hit count would score this a perfect 1.0 and
    # make it indistinguishable from finding both.
    partial = average_precision_at_k(_RANKING, {"a.md", "d.md"}, 4)
    assert partial == pytest.approx((1 / 1) / 2)
    assert partial < 1.0


def test_average_precision_denominator_is_capped_at_k() -> None:
    # Five relevant documents but k=2 chunks: at most two could ever be found,
    # so the denominator is 2 and a run that finds both scores 1.0.
    relevant = {"a.md", "b.md", "c.md", "d.md", "e.md"}
    assert average_precision_at_k(["a.md", "b.md"], relevant, 2) == pytest.approx(1.0)


def test_average_precision_is_zero_when_nothing_relevant_is_retrieved() -> None:
    assert average_precision_at_k(_RANKING, {"missing.md"}, 8) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_document_rank() -> None:
    assert reciprocal_rank_at_k(_RANKING, {"a.md"}, 8) == pytest.approx(1.0)
    assert reciprocal_rank_at_k(_RANKING, {"b.md"}, 8) == pytest.approx(1 / 2)
    # d.md is document rank 4 though its first chunk sits at chunk rank 6.
    assert reciprocal_rank_at_k(_RANKING, {"d.md"}, 8) == pytest.approx(1 / 4)
    # The earliest relevant document wins, not the highest-graded one.
    assert reciprocal_rank_at_k(_RANKING, {"b.md", "e.md"}, 8) == pytest.approx(1 / 2)


def test_reciprocal_rank_is_zero_outside_the_window() -> None:
    # d.md is document rank 4, reached only at chunk rank 6.
    assert reciprocal_rank_at_k(_RANKING, {"d.md"}, 4) == 0.0


@pytest.mark.parametrize(
    "metric",
    [recall_at_k, average_precision_at_k, reciprocal_rank_at_k],
)
def test_metrics_refuse_a_query_with_no_relevant_documents(metric) -> None:
    # Returning 0.0 would let such a query silently drag every aggregate down
    # while looking like a legitimate miss.
    with pytest.raises(ValueError, match="undefined"):
        metric(_RANKING, set(), 8)


def test_relevance_rule_admits_grades_one_and_two() -> None:
    assert not is_relevant(0)
    assert is_relevant(1)
    assert is_relevant(2)


def test_relevant_paths_reads_the_golden_set_row_shape() -> None:
    judgments = [
        {"source_path": "a.md", "grade": 2},
        {"source_path": "b.md", "grade": 1},
    ]
    assert relevant_paths(judgments) == {"a.md", "b.md"}


def test_mean_is_unweighted_and_rejects_an_empty_sequence() -> None:
    assert mean([0.0, 1.0, 0.5]) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="empty"):
        mean([])
