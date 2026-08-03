"""ORQ-21 AC5: migration up/down cleanliness against a real Postgres.

Skipped unless RAG_TEST_DATABASE_URL (a privileged/superuser DSN, asyncpg
scheme) is set -- see pytest.ini's `postgres` marker and
tests/conftest.py's pytest_collection_modifyitems skip predicate.

Not an `async def` test: alembic's `command.upgrade`/`downgrade` call
`asyncio.run()` internally (app/alembic/env.py), which raises if invoked from
inside an already-running event loop -- exactly what pytest-asyncio would
hand us with `async def`. Verification queries each open their own short-lived
event loop via `asyncio.run()` instead.

`app/alembic/env.py` reads its DSN from `settings.database_url`, not from the
Config object passed to `command.upgrade` -- `cfg.set_main_option(...)` alone
is silently overridden. The hermetic test settings singleton
(tests/conftest.py) pins `database_url` to sqlite, so this test must
monkeypatch `settings.database_url_override` to point at the real Postgres
for the duration of the migration run, or alembic would attempt Postgres DDL
against sqlite.

`env.py` also calls `logging.config.fileConfig(app/alembic.ini)` on import
(intended for the real CLI), which explicitly reconfigures the root logger
(`[logger_root]`: level=WARN, handlers=[console/StreamHandler+plain
formatter]) -- replacing whatever handler the app's structured JSON logging
or pytest's caplog had attached, for the rest of the pytest session, not just
this test. Found empirically (ORQ-21 Execution Review R1 verification):
running this test before tests/api/test_structured_logging.py or
tests/http/test_tenant_telemetry.py made them fail with zero captured
records, only when a real Postgres was reachable (RAG_TEST_DATABASE_URL set)
-- otherwise pytest_collection_modifyitems skips this whole module and the
side effect never fires. Root logger state must be saved/restored around the
alembic calls so this test's side effect stays local to itself.
"""

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
    assert url, "RAG_TEST_DATABASE_URL must be set for postgres-marked tests"
    return url


async def _fetch(query: str) -> list:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(query))).scalars().all()
    finally:
        await engine.dispose()


def test_upgrade_downgrade_leaves_no_orphans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "database_url_override", _database_url())
    cfg = Config("app/alembic.ini")

    root_logger = logging.getLogger()
    saved_handlers = list(root_logger.handlers)
    saved_level = root_logger.level

    try:
        command.upgrade(cfg, "head")
        try:
            tables = asyncio.run(_fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename IN ('documents', 'chunks')"
            ))
            assert set(tables) == {"documents", "chunks"}

            extension = asyncio.run(_fetch("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            assert extension == ["vector"]

            command.downgrade(cfg, "a1b2c3d4e5f6")

            tables = asyncio.run(_fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename IN ('documents', 'chunks')"
            ))
            assert tables == []

            # Extension is deliberately not dropped -- AC5.
            extension = asyncio.run(_fetch("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            assert extension == ["vector"]

            policies = asyncio.run(_fetch(
                "SELECT policyname FROM pg_policies WHERE tablename IN ('documents', 'chunks')"
            ))
            assert policies == []
        finally:
            command.upgrade(cfg, "head")
    finally:
        root_logger.handlers = saved_handlers
        root_logger.setLevel(saved_level)
