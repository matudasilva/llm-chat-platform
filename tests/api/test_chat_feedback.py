from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.chat_feedback import put_chat_feedback
from app.http.middleware.tenant import tenant_scope
from app.models.usage_event import UsageEvent
from app.schemas.chat import ChatFeedbackRequest


class _Scalars:
    def __init__(self, events) -> None:
        self._events = events

    def all(self):
        return self._events


class _Result:
    def __init__(self, events) -> None:
        self._events = events

    def scalars(self):
        return _Scalars(self._events)


class _Session:
    def __init__(self, events) -> None:
        self.events = events
        self.statement = None
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.events)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _event(*, feedback=None, updated_at=None) -> UsageEvent:
    return UsageEvent(
        id=uuid.uuid4(),
        provider="stub",
        model_version="stub-v1",
        prompt_version="v1",
        status="success",
        message_id=uuid.uuid4(),
        feedback=feedback,
        feedback_updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_feedback_updates_the_successful_assistant_usage_event() -> None:
    event = _event()
    db = _Session([event])

    with tenant_scope("tenant-a"):
        response = await put_chat_feedback(
            event.message_id,
            ChatFeedbackRequest(rating="up"),
            db=db,
        )

    assert response.rating == "up"
    assert response.feedback_updated_at.tzinfo is not None
    assert event.feedback == "up"
    assert db.commits == 1
    statement = str(db.statement)
    assert "messages.tenant_id" in statement
    assert "messages.role" in statement
    assert "usage_events.status" in statement


@pytest.mark.asyncio
async def test_feedback_same_rating_is_idempotent_and_keeps_timestamp() -> None:
    original = datetime(2026, 8, 6, tzinfo=timezone.utc)
    event = _event(feedback="down", updated_at=original)
    db = _Session([event])

    with tenant_scope("tenant-a"):
        response = await put_chat_feedback(
            event.message_id,
            ChatFeedbackRequest(rating="down"),
            db=db,
        )

    assert response.feedback_updated_at == original
    assert db.commits == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_feedback_changed_rating_reuses_event_and_advances_timestamp() -> None:
    original = datetime(2026, 8, 5, tzinfo=timezone.utc)
    event = _event(feedback="up", updated_at=original)
    db = _Session([event])

    with tenant_scope("tenant-a"):
        response = await put_chat_feedback(
            event.message_id,
            ChatFeedbackRequest(rating="down"),
            db=db,
        )

    assert response.rating == "down"
    assert response.feedback_updated_at > original
    assert event.status == "success"
    assert len(db.events) == 1
    assert db.commits == 1


@pytest.mark.asyncio
async def test_cross_tenant_feedback_target_is_hidden_as_not_found() -> None:
    message_id = uuid.uuid4()
    db = _Session([])

    with tenant_scope("tenant-b"):
        with pytest.raises(HTTPException) as exc_info:
            await put_chat_feedback(
                message_id,
                ChatFeedbackRequest(rating="up"),
                db=db,
            )

    assert exc_info.value.status_code == 404
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_duplicate_feedback_targets_fail_closed() -> None:
    event = _event()
    db = _Session([event, _event()])

    with tenant_scope("tenant-a"):
        with pytest.raises(HTTPException) as exc_info:
            await put_chat_feedback(
                event.message_id,
                ChatFeedbackRequest(rating="up"),
                db=db,
            )

    assert exc_info.value.status_code == 409
    assert db.commits == 0


@pytest.mark.asyncio
async def test_feedback_route_and_put_cors_contract(client) -> None:
    message_id = uuid.uuid4()
    response = await client.options(
        f"/chat/messages/{message_id}/feedback",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-tenant-id",
        },
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]
    assert "put" in client.app.openapi()["paths"][
        "/chat/messages/{message_id}/feedback"
    ]


@pytest.mark.asyncio
async def test_idempotent_feedback_uses_real_async_session_without_expired_orm_access() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    message_id = uuid.uuid4()
    original = datetime(2026, 8, 6, tzinfo=timezone.utc)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE messages ("
                    "id UUID PRIMARY KEY, conversation_id UUID NOT NULL, role VARCHAR NOT NULL, "
                    "tenant_id VARCHAR(64) NOT NULL, content TEXT NOT NULL, created_at DATETIME NOT NULL)"
                )
            )
            await connection.execute(
                text(
                    "CREATE TABLE usage_events ("
                    "id UUID PRIMARY KEY, conversation_id UUID, message_id UUID, provider VARCHAR(64) NOT NULL, "
                    "model_version VARCHAR(128) NOT NULL, prompt_version VARCHAR(64) NOT NULL, request_id UUID, "
                    "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, latency_ms INTEGER, "
                    "status VARCHAR(32), error_message TEXT, feedback VARCHAR(8), "
                    "feedback_updated_at DATETIME, timestamp DATETIME NOT NULL)"
                )
            )
        async with session_factory() as db:
            await db.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, role, tenant_id, content, created_at) "
                    "VALUES (:id, :conversation_id, 'assistant', 'tenant-a', 'answer', :created_at)"
                ),
                {
                    "id": message_id.hex,
                    "conversation_id": uuid.uuid4().hex,
                    "created_at": original,
                },
            )
            await db.execute(
                text(
                    "INSERT INTO usage_events "
                    "(id, message_id, provider, model_version, prompt_version, status, feedback, "
                    "feedback_updated_at, timestamp) "
                    "VALUES (:id, :message_id, 'stub', 'stub-v1', 'v1', 'success', 'up', "
                    ":feedback_updated_at, :timestamp)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "message_id": message_id.hex,
                    "feedback_updated_at": original,
                    "timestamp": original,
                },
            )
            await db.commit()

            with tenant_scope("tenant-a"):
                response = await put_chat_feedback(
                    message_id,
                    ChatFeedbackRequest(rating="up"),
                    db=db,
                )

            assert response.rating == "up"
            assert response.feedback_updated_at == original
    finally:
        await engine.dispose()
