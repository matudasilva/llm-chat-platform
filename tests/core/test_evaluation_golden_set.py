"""ORQ-26 AC1: the golden set is 30 bilingual pairs, frozen, and derived by a
script that refuses to produce a set violating any property the metrics rely on.

Hermetic: the derivation is a pure file transform, so none of this needs a
database, a network call, or an embedding.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from experiments.evaluation.build_golden_set import (
    GoldenSetError,
    derive,
    serialize,
)

_GROUND_TRUTH = Path("experiments/reranking/ground_truth.jsonl")
_GOLDEN_SET = Path("experiments/evaluation/golden_set.jsonl")
_CHECKSUM = Path("experiments/evaluation/golden_set.sha256")


@pytest.fixture
def ground_truth() -> list[dict]:
    return [
        json.loads(line)
        for line in _GROUND_TRUTH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_committed_golden_set_matches_the_derivation(ground_truth) -> None:
    assert _GOLDEN_SET.read_text(encoding="utf-8") == serialize(derive(ground_truth))


def test_committed_checksum_matches_the_committed_bytes() -> None:
    payload = _GOLDEN_SET.read_bytes()
    recorded = _CHECKSUM.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(payload).hexdigest() == recorded


def test_a_mutated_golden_set_breaks_the_checksum() -> None:
    # The freeze is only worth anything if a single changed byte is caught.
    mutated = _GOLDEN_SET.read_bytes().replace(b"q001", b"q999", 1)
    recorded = _CHECKSUM.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(mutated).hexdigest() != recorded


def test_shape_is_thirty_bilingual_pairs(ground_truth) -> None:
    rows = derive(ground_truth)
    assert len(rows) == 60
    assert len({row["pair_id"] for row in rows}) == 30
    assert [row["language"] for row in rows] == ["en", "es"] * 30
    assert len({row["query_id"] for row in rows}) == 60
    assert len({row["query"] for row in rows}) == 60


def test_paired_queries_carry_identical_judgments(ground_truth) -> None:
    rows = derive(ground_truth)
    by_pair: dict[str, list[dict]] = {}
    for row in rows:
        by_pair.setdefault(row["pair_id"], []).append(row)
    assert len(by_pair) == 30
    for pair_id, (english, spanish) in by_pair.items():
        assert english["relevant"] == spanish["relevant"], pair_id


def test_every_query_has_at_least_one_relevant_document(ground_truth) -> None:
    # A query with no relevant document contributes 0 to recall unconditionally
    # and would silently drag every aggregate down.
    assert all(row["relevant"] for row in derive(ground_truth))


def test_grades_are_only_one_or_two(ground_truth) -> None:
    # Grade 0 is implicit for unjudged paths and never written. This is what
    # makes the registered `>= 1` rule admit every judgment, which the ADR and
    # the README both state explicitly.
    grades = {item["grade"] for row in derive(ground_truth) for item in row["relevant"]}
    assert grades == {1, 2}


def test_relevant_documents_are_sorted_and_unique(ground_truth) -> None:
    for row in derive(ground_truth):
        paths = [item["source_path"] for item in row["relevant"]]
        assert paths == sorted(paths)
        assert len(paths) == len(set(paths))


@pytest.mark.parametrize(
    "mutate, expected",
    [
        pytest.param(
            lambda rows: rows[:-2],
            "expected 60 ground-truth rows",
            id="wrong-row-count",
        ),
        pytest.param(
            lambda rows: [rows[0], *rows[2:], rows[0]],
            "query_id values must be unique",
            id="duplicate-query-id",
        ),
        pytest.param(
            lambda rows: _with(rows, 1, language="en"),
            "expected an en/es row pair",
            id="pair-not-bilingual",
        ),
        pytest.param(
            lambda rows: _with(rows, 1, judgments=[]),
            "carry different judgments",
            id="pair-judged-differently",
        ),
        pytest.param(
            lambda rows: _with(rows, 1, query=rows[0]["query"]),
            "not distinct texts",
            id="pair-shares-query-text",
        ),
        pytest.param(
            lambda rows: _regrade(rows, 0),
            r"outside \[1, 2\]",
            id="grade-outside-scale",
        ),
        pytest.param(
            lambda rows: _repath(rows, ".framework/constitution/roadmap.md"),
            "excluded source",
            id="judgment-names-excluded-root",
        ),
    ],
)
def test_derivation_refuses_a_violating_ground_truth(ground_truth, mutate, expected) -> None:
    # The source lives in another ORQ's frozen directory, so the only correct
    # response to a violation is to refuse — never to repair it here.
    with pytest.raises(GoldenSetError, match=expected):
        derive(mutate(copy.deepcopy(ground_truth)))


def _with(rows: list[dict], index: int, **fields) -> list[dict]:
    rows[index] = {**rows[index], **fields}
    return rows


def _regrade(rows: list[dict], grade: int) -> list[dict]:
    for row in rows[:2]:
        for judgment in row["judgments"]:
            judgment["relevance"] = grade
    return rows


def _repath(rows: list[dict], source_path: str) -> list[dict]:
    for row in rows[:2]:
        row["judgments"][0]["source_path"] = source_path
    return rows
