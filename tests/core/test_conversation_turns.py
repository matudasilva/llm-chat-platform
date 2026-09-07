"""ORQ-37 T10 — total grouping, snap-back and the role-shape filter.

AC6's window half and AC16's Gate B1 portion. The B2 clauses of AC16 (every
excluded unit reaching the Mode B corpus, the `ebm25_enabled` toggle, the
frozen prompt baseline) belong to T15/T17/T18 and are not attempted here.
"""
from __future__ import annotations

import pytest

from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.conversation_turns import (
    build_materialized_window,
    group_turns,
)


def _m(*pairs) -> list[HistoryMessage]:
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


def _shapes(units):
    return [[message.role for message in unit.messages] for unit in units]


# --- §Diseño 9: the grouping rule is TOTAL on arbitrary input --------------

PATHOLOGICAL = {
    "empty": [],
    "single_user": [("user", "u")],
    "single_assistant": [("assistant", "a")],
    "single_system": [("system", "s")],
    "assistant_first": [("assistant", "a"), ("user", "u"), ("assistant", "a2")],
    "consecutive_users": [("user", "u1"), ("user", "u2"), ("assistant", "a")],
    "consecutive_assistants": [("user", "u"), ("assistant", "a1"), ("assistant", "a2")],
    "system_in_the_middle": [
        ("user", "u1"), ("assistant", "a1"),
        ("system", "s"),
        ("user", "u2"), ("assistant", "a2"),
    ],
    "odd_tail": [("user", "u1"), ("assistant", "a1"), ("user", "u2")],
    "perfect_alternation": [
        ("user", "u1"), ("assistant", "a1"), ("user", "u2"), ("assistant", "a2"),
    ],
    "all_system": [("system", "s1"), ("system", "s2")],
    "assistant_only_run": [("assistant", "a1"), ("assistant", "a2")],
}


@pytest.mark.parametrize("name", sorted(PATHOLOGICAL))
def test_grouping_is_total_and_lossless(name) -> None:
    """The property that actually proves totality.

    A list of expected shapes would only prove the cases someone thought of.
    Concatenating every unit must reproduce the input exactly, in order, for
    every input -- which is what "no input is undefined" means.
    """
    messages = _m(*PATHOLOGICAL[name])
    units = group_turns(messages)
    flattened = [message for unit in units for message in unit.messages]
    assert flattened == messages


@pytest.mark.parametrize("name", sorted(PATHOLOGICAL))
def test_every_unit_is_non_empty(name) -> None:
    assert all(unit.messages for unit in group_turns(_m(*PATHOLOGICAL[name])))


def test_user_then_assistant_forms_one_unit() -> None:
    units = group_turns(_m(("user", "u"), ("assistant", "a")))
    assert _shapes(units) == [["user", "assistant"]]
    assert units[0].is_well_formed


@pytest.mark.parametrize(
    "name,expected",
    [
        ("assistant_first", [["assistant"], ["user", "assistant"]]),
        ("consecutive_users", [["user"], ["user", "assistant"]]),
        ("consecutive_assistants", [["user", "assistant"], ["assistant"]]),
        ("odd_tail", [["user", "assistant"], ["user"]]),
        ("all_system", [["system"], ["system"]]),
    ],
)
def test_any_other_transition_emits_a_singleton(name, expected) -> None:
    assert _shapes(group_turns(_m(*PATHOLOGICAL[name]))) == expected


def test_document_text_joins_with_newline() -> None:
    unit = group_turns(_m(("user", "question"), ("assistant", "answer")))[0]
    assert unit.document_text == "question\nanswer"


def test_singleton_document_text_is_the_message() -> None:
    assert group_turns(_m(("system", "s")))[0].document_text == "s"


# --- §Diseño 8 step 2: the snap -------------------------------------------


def test_a_bound_landing_mid_turn_snaps_back_to_the_turn_start() -> None:
    messages = _m(
        ("user", "u1"), ("assistant", "a1"),
        ("user", "u2"), ("assistant", "a2"),
    )
    # The assembler's message-atomic bound kept only the assistant half.
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[3:]
    )
    assert [m.content for m in partition.window] == ["u2", "a2"]
    assert partition.snapped_in_turns == 1


def test_a_bound_already_on_a_turn_boundary_does_not_snap() -> None:
    messages = _m(
        ("user", "u1"), ("assistant", "a1"),
        ("user", "u2"), ("assistant", "a2"),
    )
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[2:]
    )
    assert [m.content for m in partition.window] == ["u2", "a2"]
    assert partition.snapped_in_turns == 0


def test_the_snap_adds_at_most_one_turn() -> None:
    # ADR-011's bounds "plus at most one snapped-in turn" (§Diseño 8 table).
    messages = _m(*[("user", f"u{i}") if i % 2 else ("assistant", f"a{i}") for i in range(1, 21)])
    for start in range(len(messages)):
        partition = build_materialized_window(
            all_messages=messages, bounded_messages=messages[start:]
        )
        assert partition.snapped_in_turns in (0, 1)


def test_no_retained_turn_is_split() -> None:
    messages = _m(
        ("user", "u1"), ("assistant", "a1"),
        ("user", "u2"), ("assistant", "a2"),
    )
    for start in range(len(messages)):
        partition = build_materialized_window(
            all_messages=messages, bounded_messages=messages[start:]
        )
        for unit in partition.window_units:
            assert len(unit.messages) == 2


# --- §Diseño 11: the filter, applied AFTER the snap -----------------------


def test_the_filter_not_the_snap_guarantees_the_shape() -> None:
    """The case that separates the two rules.

    Snapping to the start of a turn that is itself an assistant-first singleton
    yields an assistant-first window. An implementation that only snaps passes
    every test above and fails this one.
    """
    messages = _m(("assistant", "orphan"), ("user", "u1"), ("assistant", "a1"))
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    assert partition.window, "the well-formed turn must survive"
    assert partition.window[0].role == "user"
    assert "orphan" not in [m.content for m in partition.window]


def test_window_contains_no_system_row() -> None:
    messages = _m(*PATHOLOGICAL["system_in_the_middle"])
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    assert all(m.role != "system" for m in partition.window)


def test_window_begins_on_user_and_alternates() -> None:
    messages = _m(
        ("system", "s"),
        ("assistant", "orphan"),
        ("user", "u1"), ("assistant", "a1"),
        ("user", "u2"), ("assistant", "a2"),
        ("user", "odd tail"),
    )
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    roles = [m.role for m in partition.window]
    assert roles, "well-formed turns exist in this fixture"
    assert roles[0] == "user"
    assert roles == ["user", "assistant"] * (len(roles) // 2)


def test_odd_tail_is_excluded_from_the_window() -> None:
    messages = _m(("user", "u1"), ("assistant", "a1"), ("user", "pending"))
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    assert "pending" not in [m.content for m in partition.window]


# --- AC16 (B1 portion): the partition is total ---------------------------


AC16_FIXTURE = [
    ("system", "system row"),
    ("assistant", "assistant-first opening"),
    ("user", "same-role run 1"),
    ("user", "same-role run 2"),
    ("assistant", "reply"),
    ("user", "u good"), ("assistant", "a good"),
    ("user", "odd tail"),
]


def test_ac16_fixture_window_holds_only_well_formed_units() -> None:
    messages = _m(*AC16_FIXTURE)
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    assert all(unit.is_well_formed for unit in partition.window_units)
    assert [m.content for m in partition.window] == [
        "same-role run 2",
        "reply",
        "u good",
        "a good",
    ]
    assert partition.window[0].role == "user"


@pytest.mark.parametrize("start", range(len(AC16_FIXTURE)))
def test_partition_is_total_with_empty_intersection(start) -> None:
    """`bounded_grouped_history = materialized_window ⊔ complement`.

    Asserted at every possible bound, because §Diseño 8 documents an earlier
    ordering where a malformed turn inside the snap belonged to NEITHER side.
    """
    messages = _m(*AC16_FIXTURE)
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[start:]
    )
    window_ids = {id(u) for u in partition.window_units}
    excluded_ids = {id(u) for u in partition.excluded_units}
    assert window_ids & excluded_ids == set(), "a unit is on both sides"
    assert len(partition.window_units) + len(partition.excluded_units) == len(
        partition.grouped
    ), "a unit is on neither side"


@pytest.mark.parametrize("start", range(len(AC16_FIXTURE)))
def test_every_message_survives_in_exactly_one_channel(start) -> None:
    messages = _m(*AC16_FIXTURE)
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[start:]
    )
    seen = [
        message
        for unit in (*partition.window_units, *partition.excluded_units)
        for message in unit.messages
    ]
    assert sorted(m.sequence for m in seen) == [m.sequence for m in messages]


def test_units_inside_the_snapped_span_that_are_malformed_are_excluded() -> None:
    # The specific case §Diseño 8 calls out: excluded, but NOT lost.
    messages = _m(*AC16_FIXTURE)
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    excluded_contents = [
        m.content for unit in partition.excluded_units for m in unit.messages
    ]
    assert "system row" in excluded_contents
    assert "assistant-first opening" in excluded_contents
    assert "same-role run 1" in excluded_contents
    assert "odd tail" in excluded_contents


# --- degenerate inputs ----------------------------------------------------


def test_empty_history_yields_an_empty_window() -> None:
    partition = build_materialized_window(all_messages=[], bounded_messages=[])
    assert partition.window == ()
    assert partition.grouped == ()


def test_empty_bound_returns_everything_as_complement() -> None:
    messages = _m(("user", "u"), ("assistant", "a"))
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=[]
    )
    assert partition.window == ()
    assert len(partition.excluded_units) == len(partition.grouped) == 1


def test_history_with_no_well_formed_unit_yields_an_empty_window() -> None:
    messages = _m(("system", "s"), ("assistant", "a"))
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages
    )
    assert partition.window == ()
    assert len(partition.excluded_units) == 2
