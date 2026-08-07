from __future__ import annotations

import asyncio
import logging
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import settings as settings_module

pytestmark = pytest.mark.postgres


def _database_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


async def _scalar_set(query: str) -> set[str]:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect() as connection:
            return set((await connection.execute(text(query))).scalars().all())
    finally:
        await engine.dispose()


def test_usage_event_feedback_migration_is_reversible(monkeypatch) -> None:
    monkeypatch.setattr(settings_module.settings, "database_url_override", _database_url())
    config = Config("app/alembic.ini")
    root_logger = logging.getLogger()
    saved_handlers = list(root_logger.handlers)
    saved_level = root_logger.level

    try:
        command.upgrade(config, "head")
        columns = asyncio.run(
            _scalar_set(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'usage_events' "
                "AND column_name IN ('feedback', 'feedback_updated_at')"
            )
        )
        constraints = asyncio.run(
            _scalar_set(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name = 'usage_events' "
                "AND constraint_name = 'ck_usage_events_feedback'"
            )
        )
        assert columns == {"feedback", "feedback_updated_at"}
        assert constraints == {"ck_usage_events_feedback"}

        command.downgrade(config, "b7f3c9d1a204")
        assert asyncio.run(
            _scalar_set(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'usage_events' "
                "AND column_name IN ('feedback', 'feedback_updated_at')"
            )
        ) == set()
        usage_table = asyncio.run(
            _scalar_set(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = 'usage_events'"
            )
        )
        assert usage_table == {"usage_events"}
    finally:
        command.upgrade(config, "head")
        root_logger.handlers = saved_handlers
        root_logger.setLevel(saved_level)
