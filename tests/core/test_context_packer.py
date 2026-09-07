"""ORQ-37 T13 — the hard added-context cap packer (AC14).

Scope: the recent-window term only. Retrieved out-of-window evidence (B2) and
documental RAG context do not compose with this budget in this pass -- see
`context_packer.py`'s module docstring and `implementation.md`.

Every terminal case AC14 names, for the window alone:
  - within budget
  - oldest turns dropped
  - last retained turn truncated
  - an oversized-single-message case (via a giant single message inside the
    last turn -- ADR-011 §6's own permitted shape)
  - zero added context (budget <= 0, or reserved_chars consumes it all)
Byte-identical across two runs, for every case.
"""
from __future__ import annotations

import pytest

from app.core.domain.context_packer import pack_recent_window
from app.core.domain.types import ChatMessage


def _turn(user_content: str, assistant_content: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="user", content=user_content),
        ChatMessage(role="assistant", content=assistant_content),
    ]


def _window(*turns: tuple[str, str]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for user_content, assistant_content in turns:
        messages.extend(_turn(user_content, assistant_content))
    return messages


# --- terminal case: within budget, nothing happens -------------------------


def test_within_budget_is_untouched() -> None:
    window = _window(("u1", "a1"), ("u2", "a2"))
    result = pack_recent_window(window, max_chars=1_000)
    assert result.messages == tuple(window)
    assert result.truncated is False


def test_empty_window_is_untouched() -> None:
    result = pack_recent_window([], max_chars=1_000)
    assert result.messages == ()
    assert result.truncated is False


# --- terminal case: oldest complete turns dropped ---------------------------


def test_oldest_turn_is_dropped_first() -> None:
    window = _window(("old user", "old assistant"), ("new user", "new assistant"))
    budget = len("new user") + len("new assistant")
    result = pack_recent_window(window, max_chars=budget)
    assert [m.content for m in result.messages] == ["new user", "new assistant"]
    assert result.truncated is True


def test_multiple_oldest_turns_are_dropped_whole() -> None:
    window = _window(("t1u", "t1a"), ("t2u", "t2a"), ("t3u", "t3a"))
    budget = len("t3u") + len("t3a")
    result = pack_recent_window(window, max_chars=budget)
    assert [m.content for m in result.messages] == ["t3u", "t3a"]


def test_dropped_turns_never_split_a_pair() -> None:
    # A turn is dropped whole or not at all -- never one message of a pair.
    window = _window(("old user", "old assistant"), ("new user", "new assistant"))
    budget = len("new user") + len("new assistant") + 3  # not enough for both turns
    result = pack_recent_window(window, max_chars=budget)
    roles = [m.role for m in result.messages]
    assert roles == ["user", "assistant"]  # exactly one whole turn, never a lone role


# --- terminal case: last retained turn truncated ----------------------------


def test_last_retained_turn_is_truncated_deterministically() -> None:
    window = _window(("u1", "a1"), ("x" * 50, "y" * 50))
    budget = 60  # forces truncation of the sole remaining turn
    result = pack_recent_window(window, max_chars=budget)
    assert result.truncated is True
    assert sum(len(m.content) for m in result.messages) <= budget
    assert [m.role for m in result.messages] == ["user", "assistant"]


def test_truncation_never_drops_a_role_from_the_pair() -> None:
    # Even when the budget is consumed entirely by the first message of the
    # pair, the second message survives -- empty, but present and correctly
    # roled. This is the invariant, not an incidental outcome.
    window = _turn("x" * 100, "y" * 100)
    result = pack_recent_window(window, max_chars=10)
    assert len(result.messages) == 2
    assert [m.role for m in result.messages] == ["user", "assistant"]
    assert result.messages[1].content == ""


def test_truncation_keeps_the_deterministic_prefix() -> None:
    window = _turn("abcdefghij", "klmnopqrst")
    result = pack_recent_window(window, max_chars=5)
    assert result.messages[0].content == "abcde"
    assert result.messages[1].content == ""


def test_truncation_order_is_user_then_assistant() -> None:
    # Budget covers the whole user message plus part of the assistant's.
    window = _turn("short", "this is a much longer assistant reply")
    budget = len("short") + 10
    result = pack_recent_window(window, max_chars=budget)
    assert result.messages[0].content == "short"
    assert result.messages[1].content == "this is a "


# --- the oversized-single-message shape (ADR-011 §6) ------------------------


def test_an_oversized_single_message_inside_the_last_turn_is_truncated() -> None:
    # ADR-011 §6 permits the assembler to return one oversized message; T13's
    # hard cap still bounds it downstream, deterministically.
    window = _turn("normal question", "x" * 50_000)
    result = pack_recent_window(window, max_chars=12_000)
    assert sum(len(m.content) for m in result.messages) == 12_000
    assert result.messages[0].content == "normal question"
    assert len(result.messages[1].content) == 12_000 - len("normal question")


# --- terminal case: zero added context --------------------------------------


def test_zero_budget_yields_zero_added_context() -> None:
    window = _window(("u1", "a1"), ("u2", "a2"))
    result = pack_recent_window(window, max_chars=0)
    assert result.messages == ()
    assert result.truncated is True


def test_negative_effective_budget_yields_zero_added_context() -> None:
    window = _window(("u1", "a1"))
    result = pack_recent_window(window, max_chars=10, reserved_chars=100)
    assert result.messages == ()
    assert result.truncated is True


def test_zero_budget_on_an_already_empty_window_is_not_reported_as_truncated() -> None:
    # Nothing existed to drop, so this is not a truncation event.
    result = pack_recent_window([], max_chars=0)
    assert result.messages == ()
    assert result.truncated is False


def test_zero_added_context_is_a_clean_empty_tuple_not_empty_content_pairs() -> None:
    # The terminal state is genuinely ZERO messages, not a phantom turn with
    # two empty-content messages -- the distinction the module docstring
    # draws between "no room for anything" and "the last turn got truncated
    # down to nothing by accident".
    window = _window(("u1", "a1"))
    result = pack_recent_window(window, max_chars=0)
    assert len(result.messages) == 0


# --- reserved_chars: forward seam, not yet wired to anything ----------------


def test_reserved_chars_shrinks_the_effective_budget() -> None:
    window = _window(("u1", "a1"), ("u2", "a2"))
    full = pack_recent_window(window, max_chars=100)
    reserved = pack_recent_window(window, max_chars=100, reserved_chars=90)
    assert len(reserved.messages) <= len(full.messages)


def test_reserved_chars_defaults_to_zero() -> None:
    window = _window(("u1", "a1"))
    a = pack_recent_window(window, max_chars=1_000)
    b = pack_recent_window(window, max_chars=1_000, reserved_chars=0)
    assert a == b


# --- invariants asserted across every case ----------------------------------


CASES = [
    pytest.param(_window(("u1", "a1"), ("u2", "a2")), 1_000, id="within_budget"),
    pytest.param(_window(("old u", "old a"), ("new u", "new a")), 10, id="turn_dropped"),
    pytest.param(_turn("u" * 50, "a" * 50), 60, id="last_turn_truncated"),
    pytest.param(_turn("q", "x" * 50_000), 12_000, id="oversized_single_message"),
    pytest.param(_window(("u1", "a1")), 0, id="zero_added_context"),
    pytest.param([], 500, id="empty_window"),
]


@pytest.mark.parametrize("window,max_chars", CASES)
def test_roles_are_always_preserved(window, max_chars) -> None:
    result = pack_recent_window(window, max_chars=max_chars)
    for message in result.messages:
        assert message.role in ("user", "assistant")


@pytest.mark.parametrize("window,max_chars", CASES)
def test_result_never_exceeds_the_budget(window, max_chars) -> None:
    result = pack_recent_window(window, max_chars=max_chars)
    assert sum(len(m.content) for m in result.messages) <= max(max_chars, 0)


@pytest.mark.parametrize("window,max_chars", CASES)
def test_result_is_byte_identical_across_two_runs(window, max_chars) -> None:
    first = pack_recent_window(list(window), max_chars=max_chars)
    second = pack_recent_window(list(window), max_chars=max_chars)
    assert first == second


@pytest.mark.parametrize("window,max_chars", CASES)
def test_messages_always_come_in_complete_pairs(window, max_chars) -> None:
    result = pack_recent_window(window, max_chars=max_chars)
    assert len(result.messages) % 2 == 0
