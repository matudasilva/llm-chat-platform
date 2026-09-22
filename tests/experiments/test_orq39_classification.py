"""Overlap fixtures pin the total classifier's precedence."""

import json

import pytest

from experiments.conversational_semantic_memory.classification import (
    ValueEntry, ValueUniverse, classify,
)


def universe():
    return ValueUniverse((
        ValueEntry("g", frozenset({"Paris", "ＰＡＲＩＳ"}), frozenset({"gold"})),
        ValueEntry("s", frozenset({"Rome"}), frozenset({"stale"})),
        ValueEntry("c", frozenset({"Oslo"}), frozenset({"stale", "canary"})),
        ValueEntry("o", frozenset({"Lima"}), frozenset({"other"})),
    ))


@pytest.mark.parametrize("raw, expected", [
    ('{"decision":"answer","values":["Rome"],"extra":1}', "non_conforming"),
    ('{"decision":"answer","values":["Oslo"]}', "contaminated_answer"),
    ('{"decision":"answer","values":["Paris","Rome"]}', "stale_answer"),
    ('{"decision":"answer","values":["Oslo","hallucination"]}', "contaminated_answer"),
    ('{"decision":"answer","values":["Paris","hallucination"]}', "incorrect"),
    ('{"decision":"answer","values":["ＰＡＲＩＳ"]}', "correct"),
    ('{"decision":"abstain","values":[]}', "abstain"),
    ('{"decision":"answer","values":["Lima"]}', "incorrect"),
    ('{"decision":"answer","values":[]}', "incorrect"),
])
def test_precedence(raw, expected):
    assert classify(raw, universe()) == expected
    assert classify(raw.encode(), universe()) == expected


@pytest.mark.parametrize("raw", [
    '{"decision":"answer","decision":"answer","values":["Rome"]}',
    '{"decision":"answer","values":["Paris","Paris"]}',
    '{"decision":"abstain","values":["Rome"]}',
    '{"decision":[],"values":[]}', '{"decision":"answer","values":[1]}',
    '{"decision":"answer","values":[NaN]}', '[]', 'null', '{}',
    '```json\n{}\n```', '{} {}', b'\xff',
    '{"decision":"answer","values":["\\ud800"]}',
])
def test_strict_parse(raw):
    assert classify(raw, universe()) == "non_conforming"


def test_alias_collisions_rejected_at_construction():
    with pytest.raises(ValueError, match="ambiguous"):
        ValueUniverse((ValueEntry("a", frozenset({"Straße"}), frozenset({"gold"})),
                       ValueEntry("b", frozenset({"STRASSE"}), frozenset({"stale"}))))


def test_abstention_gold_and_exact_matching():
    empty = ValueUniverse(())
    assert classify(json.dumps({"decision": "abstain", "values": []}), empty) == "correct"
    assert classify('{"decision":"answer","values":[]}', empty) == "incorrect"
    for value in (" Paris", "Paris city", "Pari"):
        assert classify(json.dumps({"decision": "answer", "values": [value]}), universe()) == "incorrect"
