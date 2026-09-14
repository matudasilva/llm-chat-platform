"""ORQ-37 T15 — the Mode B retrieval corpus (AC16's partition clause, AC20's
partition clause and empty-corpus state).

Scope: the corpus is exposed and its emptiness is detectable. Selection
(BM25 ranking, "gold event selected / distractor excluded", the starved
state) is T16's -- there is nothing to select from yet, only a corpus to
select from. Not wired into the live `memory_outcome` path; see
`app/api/deps.py`'s T15 comment for why an unconditional wire would corrupt
Gate B1's own outcome distribution before Mode B is reachable.
"""
from __future__ import annotations

import pytest

from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.conversation_turns import build_materialized_window
from app.core.domain.retrieval_corpus import CorpusEvent, RetrievalCorpus


def _m(*pairs) -> list[HistoryMessage]:
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


# --- AC16 / AC20: the corpus is EXACTLY the excluded units, nothing lost ---


def test_corpus_is_built_from_the_partitions_excluded_units() -> None:
    messages = _m(
        ("system", "system row"),
        ("assistant", "assistant-first opening"),
        ("user", "u good"), ("assistant", "a good"),
        ("user", "odd tail"),
    )
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)

    corpus_texts = {event.document_text for event in corpus.events}
    assert corpus_texts == {"system row", "assistant-first opening", "odd tail"}
    # The well-formed pair belongs to the WINDOW, never the corpus.
    assert "u good" not in corpus_texts
    assert "a good" not in corpus_texts


def test_a_malformed_unit_inside_the_snapped_span_is_selectable_not_lost() -> None:
    # AC20's specific case: a malformed unit lying INSIDE the snap must still
    # reach the corpus, not disappear because the snap "covered" it.
    messages = _m(
        ("user", "u1"), ("assistant", "a1"),
        ("assistant", "orphan inside the snap"),
        ("user", "u2"), ("assistant", "a2"),
    )
    # Bound lands mid-span so the snap extends back over the orphan unit.
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[2:]
    )
    corpus = RetrievalCorpus.from_partition(partition)
    assert "orphan inside the snap" in {e.document_text for e in corpus.events}


@pytest.mark.parametrize("start", range(5))
def test_window_and_corpus_partition_totally_at_every_bound(start) -> None:
    messages = _m(
        ("system", "s"),
        ("assistant", "orphan"),
        ("user", "u1"), ("assistant", "a1"),
        ("user", "odd"),
    )
    partition = build_materialized_window(
        all_messages=messages, bounded_messages=messages[start:]
    )
    corpus = RetrievalCorpus.from_partition(partition)

    window_ids = {id(m) for m in partition.window}
    corpus_ids = {id(m) for event in corpus.events for m in event.unit.messages}
    all_ids = {id(m) for m in messages}

    assert window_ids & corpus_ids == set(), "a message is in both channels"
    assert window_ids | corpus_ids == all_ids, "a message is in neither channel"


# --- event identity, for T16 to select by -----------------------------------


def test_each_event_id_is_the_units_opening_sequence() -> None:
    messages = _m(("system", "s"), ("user", "orphan-ish"))
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)
    event_ids = {event.event_id for event in corpus.events}
    assert event_ids == {1, 2}  # each singleton's own sequence


def test_event_ids_are_unique_and_stable() -> None:
    messages = _m(("system", "s1"), ("system", "s2"), ("assistant", "a"))
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)
    ids = [event.event_id for event in corpus.events]
    assert len(ids) == len(set(ids))


def test_document_text_matches_the_underlying_units_join_rule() -> None:
    # Reuses TurnUnit.document_text (§Diseño 9's "\n".join(contents)) rather
    # than reimplementing it, so the corpus and T16's future ranking agree by
    # construction on what a document's text is.
    messages = _m(("user", "line one"), ("user", "line two"), ("assistant", "closes"))
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)
    texts = {event.document_text for event in corpus.events}
    assert "line one" in texts  # the first "user" opens a singleton (no assistant follows)


# --- AC20: the empty-corpus inert state -------------------------------------


def test_corpus_is_empty_when_the_window_covers_the_whole_conversation() -> None:
    # "a conversation entirely inside the window" (§Diseño 8's first inert
    # state): every unit is well-formed and none is excluded.
    messages = _m(("user", "u1"), ("assistant", "a1"), ("user", "u2"), ("assistant", "a2"))
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)
    assert corpus.is_empty


def test_corpus_is_non_empty_when_anything_was_excluded() -> None:
    messages = _m(("system", "s"), ("user", "u1"), ("assistant", "a1"))
    partition = build_materialized_window(all_messages=messages, bounded_messages=messages)
    corpus = RetrievalCorpus.from_partition(partition)
    assert not corpus.is_empty


def test_empty_history_yields_an_empty_corpus() -> None:
    partition = build_materialized_window(all_messages=[], bounded_messages=[])
    corpus = RetrievalCorpus.from_partition(partition)
    assert corpus.is_empty
    assert corpus.events == ()


def test_corpus_event_is_a_frozen_value_type() -> None:
    event = CorpusEvent(event_id=1, unit=build_materialized_window(
        all_messages=_m(("system", "s")), bounded_messages=_m(("system", "s"))
    ).excluded_units[0])
    with pytest.raises(Exception):
        event.event_id = 2  # type: ignore[misc]
