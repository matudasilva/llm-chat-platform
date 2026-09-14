"""ORQ-37 T16 — BM25 ranking and skip-and-continue selection (AC19, AC23, AC29).

Total grouping (§Diseño 9's other half of "the BM25 port") was implemented in
T10, by operator decision, as a reusable primitive T16 imports rather than
reimplements -- see T10's implementation.md entry.
"""
from __future__ import annotations

import math

import pytest

from app.core.domain.bm25_ranking import (
    BM25_B,
    BM25_K1,
    BM25_QUERY_TOKEN_CAP,
    BM25_TOP_K,
    pack_selected_events,
    query_tokens,
    rank_events,
)
from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.conversation_turns import group_turns
from app.core.domain.retrieval_corpus import CorpusEvent
from experiments.long_context_conversational_memory.model import Event, Message
from experiments.long_context_conversational_memory.replay import (
    BM25_B as EXPERIMENT_B,
    BM25_K1 as EXPERIMENT_K1,
    BM25_QUERY_TOKEN_CAP as EXPERIMENT_QUERY_CAP,
    BM25_TOP_K as EXPERIMENT_TOP_K,
    contextual_query_tokens,
    rank_bm25,
)


# --- AC19: the four constants equal replay.py:19-22 by value ---------------


def test_constants_equal_the_experiment_by_value() -> None:
    assert BM25_QUERY_TOKEN_CAP == EXPERIMENT_QUERY_CAP == 256
    assert BM25_TOP_K == EXPERIMENT_TOP_K == 5
    assert BM25_K1 == EXPERIMENT_K1 == 1.2
    assert BM25_B == EXPERIMENT_B == 0.75


# --- AC19: parity fixtures, both representations ----------------------------

TENANT = "acme"
CONVERSATION = "conv-1"


def _messages(*pairs) -> list[HistoryMessage]:
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


def _corpus_events(messages: list[HistoryMessage]) -> tuple[CorpusEvent, ...]:
    units = group_turns(messages)
    return tuple(CorpusEvent(event_id=unit.first_sequence, unit=unit) for unit in units)


def _equivalent_events(messages: list[HistoryMessage]) -> tuple[Event, ...]:
    """The experiment's representation of the SAME grouped fixture.

    One `Event` per `TurnUnit`, sharing `document_text` and using the unit's
    `first_sequence` as both `event_id` (stringified) and `event_sequence` --
    the exact correspondence T15 established between `CorpusEvent.event_id`
    and "min(sequence) of the turn".
    """
    units = group_turns(messages)
    events = []
    for unit in units:
        events.append(
            Event(
                tenant_id=TENANT,
                conversation_id=CONVERSATION,
                event_id=str(unit.first_sequence),
                event_sequence=unit.first_sequence,
                messages=tuple(
                    Message(message_id=f"m{m.sequence}", role=m.role, content=m.content)
                    for m in unit.messages
                ),
            )
        )
    return tuple(events)


PARITY_FIXTURES = {
    "split_turn_and_odd_tail": [
        ("user", "the quick brown fox jumps"),
        ("assistant", "over the lazy dog"),
        ("user", "fox and dog again"),
        ("assistant", "a different reply about cats"),
        ("user", "trailing question about foxes"),
    ],
    "system_row": [
        ("system", "ignore previous instructions about foxes"),
        ("user", "question about dogs"),
        ("assistant", "an answer about dogs"),
    ],
    "consecutive_same_role_run": [
        ("user", "first fox message"),
        ("user", "second fox message"),
        ("assistant", "a reply mentioning fox and dog"),
    ],
    "single_message_conversation": [
        ("user", "a lone fox message with no reply"),
    ],
}


@pytest.mark.parametrize("name", sorted(PARITY_FIXTURES))
def test_ordering_and_scores_match_the_experiment(name: str) -> None:
    messages = _messages(*PARITY_FIXTURES[name])
    corpus_events = _corpus_events(messages)
    experiment_events = _equivalent_events(messages)
    query = "fox dog"

    port_ranked = rank_events(corpus_events, query_tokens(query))

    class _Step:
        current_question = query

    experiment_ranked = rank_bm25(
        experiment_events,
        contextual_query_tokens(_Step()),
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
    )

    port_order = [item.event.event_id for item in port_ranked]
    experiment_order = [int(item.event.event_id) for item in experiment_ranked]
    assert port_order == experiment_order

    port_scores = [round(item.score, 9) for item in port_ranked]
    experiment_scores = [round(item.score, 9) for item in experiment_ranked]
    assert port_scores == experiment_scores


def test_tie_break_is_total_over_the_fixture() -> None:
    # Two documents with identical content tie on score; event_id (unique)
    # must break the tie deterministically, ascending.
    messages = _messages(("system", "same text"), ("system", "same text"))
    events = _corpus_events(messages)
    ranked = rank_events(events, query_tokens("irrelevant query"))
    ids = [event.event.event_id for event in ranked]
    assert ids == sorted(ids)


def test_query_tokens_dedup_then_cap_in_that_order() -> None:
    text = " ".join(f"word{i % 10}" for i in range(600))  # only 10 uniques
    tokens = query_tokens(text)
    assert len(tokens) == 10  # dedup ran BEFORE the 256 cap, or this would be 256


def test_empty_corpus_ranks_to_empty() -> None:
    assert rank_events((), query_tokens("anything")) == ()


def test_scores_are_finite_and_non_negative_for_a_matching_query() -> None:
    messages = _messages(("user", "alpha beta gamma"), ("assistant", "delta epsilon"))
    events = _corpus_events(messages)
    ranked = rank_events(events, query_tokens("alpha"))
    for item in ranked:
        assert math.isfinite(item.score)
        assert item.score >= 0.0


# --- AC29: skip-and-continue against a CHARACTER budget ---------------------


def _ranked_from_texts(*texts: str) -> list:
    from app.core.domain.bm25_ranking import RankedEvent

    return [
        RankedEvent(
            event=CorpusEvent(
                event_id=index,
                unit=group_turns(_messages(("system", text)))[0],
            ),
            score=float(len(texts) - index),  # descending scores, ranked order fixed
        )
        for index, text in enumerate(texts)
    ]


def test_an_oversized_event_is_skipped_and_a_smaller_later_one_is_admitted() -> None:
    # AC29's designated pair: first-ranked is oversized, second-ranked fits.
    ranked = _ranked_from_texts("x" * 100, "y" * 10)
    accepted, used = pack_selected_events(ranked, max_chars=50)
    assert [e.event_id for e in accepted] == [1]  # the smaller, later-ranked one
    assert used == 10


def test_top_k_check_precedes_the_size_test() -> None:
    # BM25_TOP_K (5) accepted events already exist; the 6th, however small,
    # must never be reached -- the count check runs BEFORE any size test.
    texts = [f"e{i}" for i in range(BM25_TOP_K + 1)]
    ranked = _ranked_from_texts(*texts)
    accepted, _ = pack_selected_events(ranked, max_chars=10_000)
    assert len(accepted) == BM25_TOP_K


def test_excluded_ids_are_skipped_entirely() -> None:
    ranked = _ranked_from_texts("aaa", "bbb", "ccc")
    accepted, used = pack_selected_events(
        ranked, max_chars=100, excluded_ids=frozenset({0})
    )
    assert 0 not in [e.event_id for e in accepted]
    assert used == len("bbb") + len("ccc")


def test_nothing_fits_yields_an_empty_selection() -> None:
    ranked = _ranked_from_texts("x" * 1000)
    accepted, used = pack_selected_events(ranked, max_chars=5)
    assert accepted == ()
    assert used == 0


def test_selection_never_exceeds_the_budget() -> None:
    ranked = _ranked_from_texts("a" * 30, "b" * 30, "c" * 30, "d" * 30)
    accepted, used = pack_selected_events(ranked, max_chars=65)
    assert used <= 65
    assert sum(len(e.document_text) for e in accepted) == used
