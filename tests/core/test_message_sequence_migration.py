"""ORQ-28: message identity ordering migration against real PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import settings as settings_module


pytestmark = pytest.mark.postgres

PREVIOUS_REVISION = "c4e9a1b2d3f4"


def _database_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


async def _execute(statement: str, **params: object) -> None:
    engine = create_async_engine(_database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _rows(statement: str, **params: object) -> list[object]:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(statement), params)).all())
    finally:
        await engine.dispose()


def test_message_sequence_migration_backfills_and_is_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "database_url_override", _database_url())
    config = Config("app/alembic.ini")
    root_logger = logging.getLogger()
    saved_handlers = list(root_logger.handlers)
    saved_level = root_logger.level
    conversation_id = UUID("44444444-4444-4444-4444-444444444444")
    existing_id = UUID("55555555-5555-5555-5555-555555555555")
    user_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    assistant_id = UUID("00000000-0000-0000-0000-000000000000")
    created_at = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    try:
        command.downgrade(config, PREVIOUS_REVISION)
        asyncio.run(
            _execute(
                "DELETE FROM messages WHERE conversation_id = :conversation_id",
                conversation_id=conversation_id,
            )
        )
        asyncio.run(
            _execute(
                "DELETE FROM conversations WHERE id = :conversation_id",
                conversation_id=conversation_id,
            )
        )
        asyncio.run(
            _execute(
                "INSERT INTO conversations (id, created_at, updated_at, tenant_id) "
                "VALUES (:id, :created_at, :created_at, 'default') "
                "ON CONFLICT (id) DO NOTHING",
                id=conversation_id,
                created_at=created_at,
            )
        )
        asyncio.run(
            _execute(
                "INSERT INTO messages (id, conversation_id, role, tenant_id, content, created_at) "
                "VALUES (:id, :conversation_id, 'user', 'default', 'existing', :created_at) "
                "ON CONFLICT (id) DO NOTHING",
                id=existing_id,
                conversation_id=conversation_id,
                created_at=created_at,
            )
        )

        command.upgrade(config, "heads")

        existing = asyncio.run(
            _rows("SELECT sequence FROM messages WHERE id = :id", id=existing_id)
        )
        assert len(existing) == 1
        assert existing[0].sequence is not None

        asyncio.run(
            _execute(
                "INSERT INTO messages (id, conversation_id, role, tenant_id, content, created_at) VALUES "
                "(:user_id, :conversation_id, 'user', 'default', 'question', :created_at), "
                "(:assistant_id, :conversation_id, 'assistant', 'default', 'answer', :created_at)",
                user_id=user_id,
                assistant_id=assistant_id,
                conversation_id=conversation_id,
                created_at=created_at,
            )
        )
        pair = asyncio.run(
            _rows(
                "SELECT id, sequence FROM messages WHERE id IN (:user_id, :assistant_id) "
                "ORDER BY sequence ASC",
                user_id=user_id,
                assistant_id=assistant_id,
            )
        )
        assert [(row.id, row.sequence) for row in pair] == [
            (user_id, pair[0].sequence),
            (assistant_id, pair[1].sequence),
        ]
        assert pair[0].sequence < pair[1].sequence

        command.downgrade(config, PREVIOUS_REVISION)
        columns = asyncio.run(
            _rows(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'messages' AND column_name = 'sequence'"
            )
        )
        assert columns == []
    finally:
        command.upgrade(config, "heads")
        asyncio.run(
            _execute(
                "DELETE FROM messages WHERE conversation_id = :conversation_id",
                conversation_id=conversation_id,
            )
        )
        asyncio.run(
            _execute(
                "DELETE FROM conversations WHERE id = :conversation_id",
                conversation_id=conversation_id,
            )
        )
        root_logger.handlers = saved_handlers
        root_logger.setLevel(saved_level)
