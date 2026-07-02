from __future__ import annotations

import os

import pytest

from app.core.settings import settings


def test_pytest_environment_is_hermetic() -> None:
    assert os.environ["APP_SETTINGS_ENV_FILE"] == ""
    assert settings.app_env == "test"
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.provider == "stub"
    assert settings.fallback_provider is None
    assert settings.notion_mcp_enabled is False
    assert settings.notion_read_enabled is False
    assert settings.notion_write_enabled is False
    assert settings.web_read_enabled is False


def test_pytest_timeout_guardrail_is_active(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.getini("timeout") == "60"
