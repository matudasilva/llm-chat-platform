from __future__ import annotations

from uuid import UUID

import pytest

from app.core.domain.conversation_history import (
    AssembledHistory,
    ConversationHistoryAssembler,
    HistoryIntegrityError,
    HistoryMessage,
)

CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
TENANT = "acme"


class _StubPort:
    """Returns canned rows. Proves the assembler's consumption, not any SQL."""

    def __init__(self, messages: list[HistoryMessage]) -> None:
        self._messages = messages
        self.calls: list[tuple[UUID, str]] = []

    async def fetch_ordered(self, conversation_id: UUID, tenant_id: str):
        self.calls.append((conversation_id, tenant_id))
        return self._messages


def _msg(sequence: int, content: str = "x", role: str = "user") -> HistoryMessage:
    return HistoryMessage(sequence=sequence, role=role, content=content)


def _assemble(messages, *, max_messages=20, max_chars=12_000):
    assembler = ConversationHistoryAssembler(
        max_messages=max_messages, max_chars=max_chars
    )
    return assembler.assemble(_StubPort(messages), CONVERSATION_ID, TENANT)


# --- AC2: order preserved, strict monotonicity enforced ---


@pytest.mark.asyncio
async def test_preserves_port_order_and_never_resorts() -> None:
    messages = [_msg(10, "a"), _msg(20, "b"), _msg(30, "c")]
    result = await _assemble(messages)
    assert [m.sequence for m in result.messages] == [10, 20, 30]
    assert [m.content for m in result.messages] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_raises_on_decreasing_sequence() -> None:
    with pytest.raises(HistoryIntegrityError):
        await _assemble([_msg(20), _msg(10)])


@pytest.mark.asyncio
async def test_raises_on_equal_adjacent_sequence() -> None:
    # Strict, not merely non-decreasing: equal ordering keys are a contract
    # violation regardless of what the schema permits.
    with pytest.raises(HistoryIntegrityError):
        await _assemble([_msg(10), _msg(10)])


@pytest.mark.asyncio
async def test_validates_before_bounding() -> None:
    # The violation sits among messages the message cap would drop. Validating
    # after truncation would miss it.
    messages = [_msg(30), _msg(20), _msg(40), _msg(50)]
    with pytest.raises(HistoryIntegrityError):
        await _assemble(messages, max_messages=2)


# --- AC3: field sets are exactly what the spec fixes them at ---


def test_assembled_history_field_set_is_exact() -> None:
    import dataclasses

    assert tuple(f.name for f in dataclasses.fields(AssembledHistory)) == (
        "messages",
        "total_available",
        "truncated",
    )


def test_history_message_field_set_is_exact() -> None:
    import dataclasses

    assert tuple(f.name for f in dataclasses.fields(HistoryMessage)) == (
        "sequence",
        "role",
        "content",
    )


def test_domain_module_has_no_created_at_reference() -> None:
    from pathlib import Path

    import app.core.domain.conversation_history as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    # Named only in the docstring explaining why it is absent as a field.
    assert "created_at: " not in source
    assert "self.created_at" not in source


# --- AC9: every row of the bounds table ---


@pytest.mark.asyncio
async def test_char_cap_is_inclusive() -> None:
    result = await _assemble([_msg(1, "abcde")], max_chars=5)
    assert len(result.messages) == 1
    assert result.truncated is False


@pytest.mark.asyncio
async def test_bisecting_message_is_dropped_whole() -> None:
    result = await _assemble([_msg(1, "aaaa"), _msg(2, "bb")], max_chars=4)
    assert [m.content for m in result.messages] == ["bb"]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_single_oversized_message_is_returned_with_cap_exceeded() -> None:
    result = await _assemble([_msg(1, "aaaaaaaaaa")], max_chars=3)
    assert len(result.messages) == 1
    # Nothing was dropped, so truncated is False even though the cap is over.
    assert result.truncated is False
    assert result.total_available == 1


@pytest.mark.asyncio
async def test_char_cap_unsatisfiable_keeps_single_newest() -> None:
    # Every message alone exceeds the cap. The loop stops at one message,
    # never at "cap satisfied".
    result = await _assemble(
        [_msg(1, "aaaa"), _msg(2, "bbbb"), _msg(3, "cccc")], max_chars=2
    )
    assert [m.content for m in result.messages] == ["cccc"]
    assert result.truncated is True
    assert result.total_available == 3


@pytest.mark.asyncio
async def test_exactly_max_messages_with_char_cap_binding() -> None:
    result = await _assemble([_msg(1, "aaa"), _msg(2, "bbb")], max_messages=2, max_chars=3)
    assert [m.content for m in result.messages] == ["bbb"]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_exactly_max_messages_neither_cap_binds() -> None:
    result = await _assemble([_msg(1, "a"), _msg(2, "b")], max_messages=2, max_chars=100)
    assert result.total_available == 2
    assert result.truncated is False


@pytest.mark.asyncio
async def test_empty_history() -> None:
    # Assembler-level only: the adapter cannot produce this, since a missing
    # conversation raises instead.
    result = await _assemble([])
    assert result.messages == ()
    assert result.total_available == 0
    assert result.truncated is False


@pytest.mark.asyncio
async def test_message_cap_is_applied_before_char_cap() -> None:
    # If the char cap ran first it would drop from the oldest end of all four
    # and could leave a different survivor set than capping to two first.
    messages = [_msg(1, "aaaa"), _msg(2, "bbbb"), _msg(3, "cc"), _msg(4, "dd")]
    result = await _assemble(messages, max_messages=2, max_chars=4)
    assert [m.content for m in result.messages] == ["cc", "dd"]
    assert result.total_available == 4
    assert result.truncated is True


@pytest.mark.asyncio
async def test_total_available_is_pre_truncation() -> None:
    messages = [_msg(i, "x") for i in range(1, 11)]
    result = await _assemble(messages, max_messages=3)
    assert result.total_available == 10
    assert len(result.messages) == 3


@pytest.mark.asyncio
async def test_port_receives_tenant_id() -> None:
    port = _StubPort([_msg(1)])
    assembler = ConversationHistoryAssembler(max_messages=5, max_chars=100)
    await assembler.assemble(port, CONVERSATION_ID, TENANT)
    assert port.calls == [(CONVERSATION_ID, TENANT)]
