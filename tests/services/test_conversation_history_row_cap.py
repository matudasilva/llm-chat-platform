"""ORQ-37 T12 — the operational history read, bounded in SQL (AC36).

`ConversationQueryService.list_recent_messages_for_conversation` and
`SqlConversationHistoryAdapter`'s optional `max_rows`. `AC15` (the index
migration itself, with `EXPLAIN`/latency) is a separate file --
`test_conversation_history_index_migration.py` -- because it needs no
database at all and this one is deliberately kept to compiled-SQL and
in-memory fixtures for the same reason.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.domain.conversation_history import ConversationNotFoundError
from app.models.message import MessageRole
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService

pytestmark = pytest.mark.asyncio

CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
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


def _row(sequence: int, role: MessageRole = MessageRole.user, content: str = "x"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        sequence=sequence,
        conversation_id=CONVERSATION_ID,
        tenant_id=TENANT,
        role=role,
        content=content,
        created_at=CREATED_AT,
    )


def _compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).replace('"', "")


# --- AC36: the compiled SQL itself ------------------------------------------


async def test_recent_read_carries_limit_and_desc_order() -> None:
    session = _RecordingSession([[]])
    await ConversationQueryService(session).list_recent_messages_for_conversation(
        CONVERSATION_ID, TENANT, max_rows=2_000
    )
    sql = _compiled(session.statements[0])
    assert "LIMIT" in sql
    assert "ORDER BY messages.sequence DESC" in sql


async def test_limit_value_is_bound_to_max_rows() -> None:
    session = _RecordingSession([[]])
    await ConversationQueryService(session).list_recent_messages_for_conversation(
        CONVERSATION_ID, TENANT, max_rows=37
    )
    compiled = session.statements[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    assert "LIMIT 37" in str(compiled)


async def test_unbounded_read_carries_no_limit() -> None:
    # The existing method, untouched: no LIMIT, ASC order, still available for
    # whatever other consumer needs the whole conversation.
    session = _RecordingSession([[]])
    await ConversationQueryService(session).list_messages_for_conversation(
        CONVERSATION_ID, TENANT
    )
    sql = _compiled(session.statements[0])
    assert "LIMIT" not in sql
    assert "ORDER BY messages.sequence ASC" in sql


async def test_result_is_re_sorted_ascending() -> None:
    # The DB returns DESC (newest first); the service must hand back ASC.
    session = _RecordingSession([[_row(30), _row(20), _row(10)]])
    rows = await ConversationQueryService(session).list_recent_messages_for_conversation(
        CONVERSATION_ID, TENANT, max_rows=3
    )
    assert [r.sequence for r in rows] == [10, 20, 30]


async def test_takes_the_most_recent_not_the_oldest() -> None:
    # An `ORDER BY sequence ASC LIMIT n` would silently return the OLDEST n
    # instead -- the exact bug AC36 exists to prevent. Simulated here by
    # having the double return what the real DESC+LIMIT query would: the
    # newest `max_rows` rows, DESC.
    session = _RecordingSession([[_row(5), _row(4), _row(3)]])  # DESC, top-3 of 5
    rows = await ConversationQueryService(session).list_recent_messages_for_conversation(
        CONVERSATION_ID, TENANT, max_rows=3
    )
    assert [r.sequence for r in rows] == [3, 4, 5]
    assert 1 not in [r.sequence for r in rows]
    assert 2 not in [r.sequence for r in rows]


async def test_result_is_deterministic_across_runs() -> None:
    for _ in range(2):
        session = _RecordingSession([[_row(30), _row(20), _row(10)]])
        rows = await ConversationQueryService(
            session
        ).list_recent_messages_for_conversation(CONVERSATION_ID, TENANT, max_rows=3)
        assert [r.sequence for r in rows] == [10, 20, 30]


# --- the adapter: additive, default-preserving ------------------------------


async def test_adapter_default_is_unbounded_and_unchanged() -> None:
    # ORQ-38's original behaviour, byte for byte: no max_rows means no LIMIT.
    session = _RecordingSession([_conversation(), [_row(1), _row(2)]])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session))
    await adapter.fetch_ordered(CONVERSATION_ID, TENANT)
    sql = _compiled(session.statements[1])
    assert "LIMIT" not in sql


async def test_adapter_with_max_rows_uses_the_bounded_query() -> None:
    session = _RecordingSession([_conversation(), [_row(1), _row(2)]])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session), max_rows=2_000)
    await adapter.fetch_ordered(CONVERSATION_ID, TENANT)
    sql = _compiled(session.statements[1])
    assert "LIMIT" in sql


async def test_adapter_still_raises_for_a_foreign_conversation_when_bounded() -> None:
    # AC10's contract is unaffected by T12: ownership is still checked first.
    session = _RecordingSession([None])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session), max_rows=2_000)
    with pytest.raises(ConversationNotFoundError):
        await adapter.fetch_ordered(CONVERSATION_ID, "other-tenant")
    assert len(session.statements) == 1, "the bounded query must not run before ownership is checked"


async def test_adapter_maps_role_value_the_same_way_when_bounded() -> None:
    session = _RecordingSession([_conversation(), [_row(1, role=MessageRole.assistant, content="hi")]])
    adapter = SqlConversationHistoryAdapter(ConversationQueryService(session), max_rows=10)
    messages = await adapter.fetch_ordered(CONVERSATION_ID, TENANT)
    assert messages[0].role == "assistant"
    assert isinstance(messages[0].role, str)


# --- AC36: the at-cap fixture, run twice and compared -----------------------


@pytest.fixture
def at_cap_session():
    # A conversation with exactly `max_rows` messages: the read is AT the cap,
    # not merely bounded by an unreached ceiling.
    rows_desc = [_row(sequence) for sequence in range(5, 0, -1)]  # 5..1, DESC
    return lambda: _RecordingSession([_conversation(), list(rows_desc)])


async def test_at_cap_fixture_is_deterministic_across_two_runs(at_cap_session) -> None:
    max_rows = 5
    results = []
    for _ in range(2):
        adapter = SqlConversationHistoryAdapter(
            ConversationQueryService(at_cap_session()), max_rows=max_rows
        )
        messages = await adapter.fetch_ordered(CONVERSATION_ID, TENANT)
        results.append(tuple((m.sequence, m.content) for m in messages))
    assert results[0] == results[1]
    assert [seq for seq, _ in results[0]] == [1, 2, 3, 4, 5]
