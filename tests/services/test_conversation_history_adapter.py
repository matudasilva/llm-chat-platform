from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.core.domain.conversation_history import ConversationNotFoundError
from app.models.message import MessageRole
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService

CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
TENANT = "acme"
CREATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values if isinstance(self._values, list) else []

    def scalar_one_or_none(self):
        return self._values if not isinstance(self._values, list) else None


class _RecordingSession:
    def __init__(self, results):
        self.statements = []
        self._results = list(results)

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult(self._results.pop(0))


def _conversation():
    return SimpleNamespace(id=CONVERSATION_ID, tenant_id=TENANT)


def _row(sequence: int, role: MessageRole, content: str):
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        sequence=sequence,
        conversation_id=CONVERSATION_ID,
        tenant_id=TENANT,
        role=role,
        content=content,
        created_at=CREATED_AT,
    )


def _compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).replace('"', "")


# --- AC6: Layer 1 ownership guard, unconditional ---


@pytest.mark.asyncio
async def test_raises_when_conversation_is_not_owned() -> None:
    # get_conversation returns None on a tenant mismatch (ADR-004 §2).
    session = _RecordingSession([None])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))

    with pytest.raises(ConversationNotFoundError):
        await adapter.fetch_ordered(CONVERSATION_ID, "other-tenant")

    # The message query must never have been issued.
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_never_returns_empty_for_an_unowned_conversation() -> None:
    # An empty return would be indistinguishable from an empty conversation,
    # which is how isolation gets lost silently.
    session = _RecordingSession([None])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
    with pytest.raises(ConversationNotFoundError):
        await adapter.fetch_ordered(CONVERSATION_ID, "other-tenant")


@pytest.mark.asyncio
async def test_ownership_guard_precedes_the_message_read() -> None:
    session = _RecordingSession([_conversation(), [_row(1, MessageRole.user, "hi")]])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
    await adapter.fetch_ordered(CONVERSATION_ID, TENANT)

    assert "FROM conversations" in _compiled(session.statements[0])
    assert "FROM messages" in _compiled(session.statements[1])


# --- AC7: mapping glue, and the role type footgun ---


@pytest.mark.asyncio
async def test_maps_rows_to_history_messages() -> None:
    session = _RecordingSession(
        [
            _conversation(),
            [_row(41, MessageRole.user, "question"), _row(42, MessageRole.assistant, "answer")],
        ]
    )
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
    messages = await adapter.fetch_ordered(CONVERSATION_ID, TENANT)

    assert [m.sequence for m in messages] == [41, 42]
    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.content for m in messages] == ["question", "answer"]


@pytest.mark.asyncio
async def test_role_is_a_plain_str_not_the_enum_member() -> None:
    # MessageRole subclasses str, so == would pass with the member left in
    # place. Only the exact type check catches a passthrough.
    session = _RecordingSession([_conversation(), [_row(1, MessageRole.user, "hi")]])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
    messages = await adapter.fetch_ordered(CONVERSATION_ID, TENANT)

    assert type(messages[0].role) is str


# --- AC5: compiled SQL, Layer 2 shipped (T3 measured 0) ---


@pytest.mark.asyncio
async def test_message_query_filters_conversation_and_tenant_and_orders_by_sequence() -> None:
    session = _RecordingSession([[_row(1, MessageRole.user, "hi")]])
    await ConversationQueryService(session).list_messages_for_conversation(
        CONVERSATION_ID, TENANT
    )
    sql = _compiled(session.statements[0])

    where = sql.split("WHERE", maxsplit=1)[1]
    assert "messages.conversation_id" in where
    assert "messages.tenant_id" in where
    assert sql.split("ORDER BY", maxsplit=1)[1].strip().startswith("messages.sequence ASC")
