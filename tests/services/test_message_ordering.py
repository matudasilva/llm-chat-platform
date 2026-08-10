from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.models.message import MessageRole
from app.services.conversation_query_service import ConversationQueryService
from app.services.trace import TraceService


CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
REQUEST_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
ASSISTANT_ID = UUID("00000000-0000-0000-0000-000000000000")
CREATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class _ScalarResult:
    def __init__(self, values: list[object] | object | None) -> None:
        self._values = values

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return self._values if isinstance(self._values, list) else []

    def scalar_one_or_none(self) -> object | None:
        return self._values if not isinstance(self._values, list) else None


class _RecordingSession:
    def __init__(self, results: list[list[object] | object | None]) -> None:
        self.statements = []
        self._results = list(results)

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult(self._results.pop(0))


def _message(*, id: UUID, role: MessageRole, sequence: int, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        sequence=sequence,
        conversation_id=CONVERSATION_ID,
        role=role,
        content=content,
        created_at=CREATED_AT,
    )


def _order_by_sql(statement) -> str:
    sql = str(statement.compile(dialect=postgresql.dialect())).replace('"', "")
    return sql.split("ORDER BY", maxsplit=1)[1]


@pytest.mark.asyncio
async def test_conversation_query_orders_equal_timestamps_by_sequence_not_uuid() -> None:
    user = _message(id=USER_ID, role=MessageRole.user, sequence=41, content="question")
    assistant = _message(id=ASSISTANT_ID, role=MessageRole.assistant, sequence=42, content="answer")
    session = _RecordingSession([[user, assistant]])

    messages = await ConversationQueryService(session).list_messages_for_conversation(
        CONVERSATION_ID,
        "default",
    )

    assert [message.id for message in messages] == [USER_ID, ASSISTANT_ID]
    order_by = _order_by_sql(session.statements[0])
    assert "messages.sequence ASC" in order_by
    assert "created_at" not in order_by
    assert "messages.id" not in order_by


@pytest.mark.asyncio
async def test_trace_orders_and_reconstructs_equal_timestamps_by_sequence_not_uuid() -> None:
    user = _message(id=USER_ID, role=MessageRole.user, sequence=41, content="question")
    assistant = _message(id=ASSISTANT_ID, role=MessageRole.assistant, sequence=42, content="answer")
    event = SimpleNamespace(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        conversation_id=CONVERSATION_ID,
        message_id=ASSISTANT_ID,
        provider="stub",
        model_version="stub-v1",
        prompt_version="v1",
        request_id=REQUEST_ID,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1,
        status="success",
        error_message=None,
        feedback=None,
        feedback_updated_at=None,
        timestamp=CREATED_AT,
    )
    conversation = SimpleNamespace(
        id=CONVERSATION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        title=None,
    )
    session = _RecordingSession([[event], conversation, [user, assistant]])

    report = await TraceService.reconstruct_by_request_id(session, REQUEST_ID)

    assert report.messages is not None
    assert [message.id for message in report.messages] == [USER_ID, ASSISTANT_ID]
    assert report.reconstruction is not None
    assert report.reconstruction.input_message is not None
    assert report.reconstruction.output_message is not None
    assert report.reconstruction.input_message.id == USER_ID
    assert report.reconstruction.output_message.id == ASSISTANT_ID
    order_by = _order_by_sql(session.statements[2])
    assert "messages.sequence ASC" in order_by
    assert "created_at" not in order_by
    assert "messages.id" not in order_by
