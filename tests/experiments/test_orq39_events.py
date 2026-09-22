from __future__ import annotations

import json

import pytest

from experiments.conversational_semantic_memory import events


def test_chain_links_each_event_to_its_predecessor(tmp_path) -> None:
    log = tmp_path / "events.jsonl"
    first = events.append(log, "heldout_pool_sealed", {"sha256": "a" * 64})
    second = events.append(log, "oow_check_dev", {"result_sha256": "b" * 64})

    assert first.previous == events.GENESIS_PREVIOUS
    assert second.previous == first.hash
    assert [event.type for event in events.verify(log)] == [
        "heldout_pool_sealed",
        "oow_check_dev",
    ]


def test_missing_log_is_an_empty_chain_not_an_error(tmp_path) -> None:
    assert events.verify(tmp_path / "absent.jsonl") == ()


@pytest.mark.parametrize(
    "tamper",
    [
        lambda rows: rows[0].update(payload={"sha256": "c" * 64}),  # edited payload
        lambda rows: rows.reverse(),  # reordered
        lambda rows: rows[1].update(seq=5),  # sequence gap
        lambda rows: rows.pop(0),  # first event removed
    ],
)
def test_any_edit_reorder_or_removal_fails_closed(tmp_path, tamper) -> None:
    log = tmp_path / "events.jsonl"
    events.append(log, "a_event", {"n": 1})
    events.append(log, "b_event", {"n": 2})
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    tamper(rows)
    log.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(events.EventLogError):
        events.verify(log)


def test_truncated_final_write_fails_closed(tmp_path) -> None:
    log = tmp_path / "events.jsonl"
    events.append(log, "a_event", {"n": 1})
    log.write_text(log.read_text().rstrip("\n"))

    with pytest.raises(events.EventLogError, match="truncated"):
        events.verify(log)


def test_append_refuses_to_extend_a_corrupt_chain(tmp_path) -> None:
    log = tmp_path / "events.jsonl"
    events.append(log, "a_event", {"n": 1})
    log.write_text(log.read_text().replace('"n":1', '"n":2'))

    with pytest.raises(events.EventLogError):
        events.append(log, "b_event", {"n": 3})


def test_precedes_orders_by_chain_position(tmp_path) -> None:
    log = tmp_path / "events.jsonl"
    events.append(log, "freeze", {})
    events.append(log, "dispatch", {})
    chain = events.verify(log)

    def is_type(name):
        return lambda event: event.type == name

    assert events.precedes(chain, is_type("freeze"), is_type("dispatch"))
    assert not events.precedes(chain, is_type("dispatch"), is_type("freeze"))
    # The obligation only binds once the later stage exists, but the earlier
    # event must still have been recorded.
    assert events.precedes(chain, is_type("freeze"), is_type("never"))
    assert not events.precedes(chain, is_type("never"), is_type("dispatch"))


def test_invalid_event_type_is_rejected(tmp_path) -> None:
    with pytest.raises(events.EventLogError):
        events.append(tmp_path / "events.jsonl", "Not-Valid", {})
