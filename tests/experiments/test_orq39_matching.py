"""Value matching, unmatched detection, and alias collision invariants."""

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


def test_unmatched_and_alias_collisions():
    """Test that unmatched values are rejected and alias collisions fail at construction."""
    # Unmatched values: gold-complete answer with extra unmatched value is incorrect
    assert classify('{"decision":"answer","values":["Paris","hallucination"]}', universe()) == "incorrect"

    # Unmatched partial matches
    for value in (" Paris", "Paris city", "Pari"):
        assert classify(json.dumps({"decision": "answer", "values": [value]}), universe()) == "incorrect"

    # Exact matching only
    assert classify('{"decision":"answer","values":["ＰＡＲＩＳ"]}', universe()) == "correct"

    # Empty value list is unmatched
    assert classify('{"decision":"answer","values":[]}', universe()) == "incorrect"

    # Alias collisions are rejected at construction
    with pytest.raises(ValueError, match="ambiguous"):
        ValueUniverse((ValueEntry("a", frozenset({"Straße"}), frozenset({"gold"})),
                       ValueEntry("b", frozenset({"STRASSE"}), frozenset({"stale"}))))
