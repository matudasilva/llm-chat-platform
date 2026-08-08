"""ORQ-26 AC6: the evaluation store DSN cannot be the application database.

Hermetic — Settings validation only, no connection is opened.
"""

from __future__ import annotations

import pytest

from app.core.settings import Settings

_SUPERUSER_DSN = "postgresql+asyncpg://owner:secret@db:5432/llmchat"


def _settings(**overrides) -> Settings:
    return Settings(
        app_env="test",
        DATABASE_URL=_SUPERUSER_DSN,
        PRIMARY_PROVIDER="stub",
        **overrides,
    )


def test_store_url_is_inert_by_default() -> None:
    assert _settings().evaluation_store_url is None


def test_store_url_equal_to_the_application_database_is_rejected() -> None:
    # The failure this drifts into: the superuser DSN is already in the
    # environment and it works, so a harness that "just needs a connection"
    # would silently gain a write path into business data.
    with pytest.raises(ValueError, match="must not equal the application database URL"):
        _settings(EVALUATION_STORE_URL=_SUPERUSER_DSN)


def test_a_distinct_store_url_is_accepted() -> None:
    dsn = "postgresql+asyncpg://rag_evaluation:secret@db:5432/llmchat"
    assert _settings(EVALUATION_STORE_URL=dsn).evaluation_store_url == dsn


def test_the_rag_app_url_is_deliberately_not_rejected() -> None:
    # rag_app is under-privileged, not over-privileged: it cannot CREATE SCHEMA,
    # so pointing the store at it fails loudly at DDL time rather than
    # succeeding dangerously. Guarding it here would guard the wrong direction
    # (ADR-009 decision 5).
    app_dsn = "postgresql+asyncpg://rag_app:secret@db:5432/llmchat"
    settings = _settings(DATABASE_URL_APP=app_dsn, EVALUATION_STORE_URL=app_dsn)
    assert settings.evaluation_store_url == app_dsn
