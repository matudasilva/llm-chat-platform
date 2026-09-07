"""ORQ-37 T14 — settings validators and shipped defaults."""
from __future__ import annotations

import pytest

from app.core.settings import Settings


def _settings(**overrides):
    base = dict(
        app_env="test",
        DATABASE_URL="postgresql+asyncpg://primary/db",
        PRIMARY_PROVIDER="stub",
        FALLBACK_PROVIDER=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_shipped_defaults_are_inert() -> None:
    settings = _settings()
    assert settings.rag_request_metrics_enabled is False
    assert settings.rag_request_metrics_retention_days == 30
    assert settings.rag_request_metrics_timeout_s > 0


@pytest.mark.parametrize("days", [0, -1, -30])
def test_retention_days_rejects_non_positive(days) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        _settings(rag_request_metrics_retention_days=days)


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_timeout_rejects_non_positive(value) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        _settings(rag_request_metrics_timeout_s=value)


def test_retention_days_accepts_a_positive_override() -> None:
    settings = _settings(rag_request_metrics_retention_days=90)
    assert settings.rag_request_metrics_retention_days == 90
