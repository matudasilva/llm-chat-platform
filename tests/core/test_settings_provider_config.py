import pytest

from app.core.settings import Settings


def test_settings_accept_valid_provider_config() -> None:
    settings = Settings(
        provider="stub",
        provider_timeout_s=30.0,
        stub_provider_mode="ok",
        stub_simulated_latency_ms=0,
        openai_max_attempts=3,
        openai_backoff_base_ms=200,
        openai_backoff_max_ms=2000,
    )

    assert settings.provider == "stub"
    assert settings.provider_timeout_s == 30.0


def test_settings_reject_invalid_provider() -> None:
    with pytest.raises(ValueError, match="provider must be one of"):
        Settings(provider="invalid-provider")


def test_settings_reject_invalid_stub_mode() -> None:
    with pytest.raises(ValueError, match="stub_provider_mode must be one of"):
        Settings(stub_provider_mode="invalid-mode")


def test_settings_reject_invalid_backoff_relationship() -> None:
    with pytest.raises(ValueError, match="openai_backoff_max_ms must be >="):
        Settings(
            openai_backoff_base_ms=500,
            openai_backoff_max_ms=100,
        )