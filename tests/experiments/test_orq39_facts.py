"""Pin fact identities and pure lifecycle behavior independently of providers."""

from dataclasses import asdict
import json

import pytest

from experiments.conversational_semantic_memory.events import canonical_bytes
from experiments.conversational_semantic_memory.facts import FactStore, Operation, apply, fact_id

EXPECTED = (
    "bf7e212a1c85ead14f477a919a25de1aff2091264695afd3b57eedc12badc8d3",
    "3b882c4305bba2836a54944cb4d331abd9dc364ab5eec6ff4e88055adb90fb0f",
    "3fdce6fa2635646085636e43c9692d341a66f39f7e2d6593b025a1ae1f32e6c1",
)


def operation(value, source="message", slot="home_city", kind="stable_fact"):
    return Operation("assert" if value is not None else "retract", slot, value, kind, (source,))


def store():
    return FactStore("tenant", "conversation", "extractor-v1")


def chain():
    result = store()
    for seq, value in enumerate(("v1", "v2", "v3", None), 1):
        result = apply(result, (operation(value, f"m{seq}"),), source_sequence=seq,
                       statement=f"Source assertion {seq}")
    return result


def test_multistep_chain_distinct_ids_and_inverse_links():
    result = chain()
    assert tuple(f.fact_id for f in result.facts) == EXPECTED
    assert tuple(f.status for f in result.facts) == ("superseded", "superseded", "retracted")
    assert tuple(f.supersedes for f in result.facts) == (None, EXPECTED[0], EXPECTED[1])
    assert tuple(f.superseded_by for f in result.facts) == (EXPECTED[1], EXPECTED[2], None)
    assert canonical_bytes(asdict(result)) == canonical_bytes(asdict(chain()))


def test_dedup_noop_and_reassertion():
    original = store()
    first = apply(original, (operation("Café"),), source_sequence=1, statement="I said Café")
    duplicate = apply(first, (operation("  CAFE\u0301 ", "m2"),), source_sequence=2, statement="Repeated")
    assert original.facts == ()
    assert first.facts[0].source_message_ids == ("message",)
    assert duplicate.facts[0].source_message_ids == ("message", "m2")
    assert duplicate.facts[0].source_sequence == 1
    assert duplicate.facts[0].fact_id == first.facts[0].fact_id
    retracted = apply(duplicate, (operation(None),), source_sequence=3, statement="Retracted")
    noop = apply(retracted, (operation(None),), source_sequence=4, statement="Retracted again")
    assert noop.facts == retracted.facts
    assert noop.audit[0].reason == "retract_without_active_fact"
    assert "timestamp" not in json.dumps(asdict(noop))
    new = apply(noop, (operation("Café"),), source_sequence=5, statement="Asserted again")
    assert new.facts[-1].supersedes is None
    assert new.facts[-1].fact_id != first.facts[0].fact_id


def test_same_turn_operation_index_and_forward_only_order():
    result = apply(store(), (operation("a"), operation("b")), source_sequence=1, statement="Correction")
    assert result.facts[0].fact_id != result.facts[1].fact_id
    assert result.facts[0].superseded_by == result.facts[1].fact_id
    for seq in (0, 1):
        with pytest.raises(ValueError, match="advance"):
            apply(result, (), source_sequence=seq, statement="Repeated turn")


def test_adversarial_fact_id_boundaries():
    def identifier(tenant, conversation):
        return fact_id(tenant, conversation, "slot", 1, 0)
    assert identifier("a|b", "c") != identifier("a", "b|c")
    assert identifier('a\",\"conversation_id\":\"b', "c") != identifier("a", 'b\",\"conversation_id\":\"c')
    assert identifier("é", "x") == identifier("e\u0301", "x")
    assert identifier("e", "\u0301x") != identifier("é", "x")
    assert identifier("Ａ", "x") != identifier("A", "x")
    assert fact_id("a", "b", "slot", 1, 23) != fact_id("a", "b", "slot", 12, 3)
    with pytest.raises(ValueError):
        fact_id("a", "b", "slot", True, 0)


def test_scope_and_slot_drift_remain_distinct():
    assert fact_id("t1", "c", "slot", 1, 0) != fact_id("t2", "c", "slot", 1, 0)
    assert fact_id("t", "c1", "slot", 1, 0) != fact_id("t", "c2", "slot", 1, 0)
    result = apply(store(), (operation("Paris"), operation("Paris", slot="city")),
                   source_sequence=1, statement="Paris")
    assert len(result.facts) == 2
    assert all(f.status == "active" for f in result.facts)


def test_prohibited_is_audited_never_stored():
    result = apply(store(), (operation("SYNTHETIC-PROHIBITED-ABC-1234abcd", kind="prohibited"),),
                   source_sequence=1, statement="Synthetic fixture")
    assert result.facts == ()
    assert result.audit[0].reason == "prohibited"


@pytest.mark.parametrize("changes", [
    {"op": "update"}, {"slot_key": "Home City"}, {"kind": "unknown"},
    {"source_message_ids": ()}, {"value": None}, {"op": "retract", "value": "x"},
])
def test_invalid_operations_rejected(changes):
    fields = dict(op="assert", slot_key="home_city", value="Paris", kind="stable_fact",
                  source_message_ids=("m1",))
    with pytest.raises(ValueError):
        Operation(**(fields | changes))


def test_extractor_objects_and_atomic_validation():
    payload = {"op": "assert", "slot_key": "home_city", "value": "Paris",
               "kind": "stable_fact", "source_message_ids": ["m1"]}
    original = store()
    result = apply(original, [payload], source_sequence=1, statement="I live in Paris")
    assert result.facts[0].value == "Paris"
    with pytest.raises(ValueError, match="unexpected operation fields"):
        apply(original, [payload, payload | {"status": "active"}],
              source_sequence=1, statement="I live in Paris")
    assert original.facts == ()
