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


def test_settings_accept_valid_bedrock_provider_config() -> None:
    settings = Settings(
        provider="bedrock",
        provider_timeout_s=30.0,
        bedrock_region="us-east-1",
        bedrock_model="anthropic.claude-3-haiku-20240307-v1:0",
        bedrock_max_attempts=3,
        bedrock_backoff_base_ms=200,
        bedrock_backoff_max_ms=2000,
    )

    assert settings.provider == "bedrock"
    assert settings.bedrock_region == "us-east-1"
    assert settings.bedrock_model == "anthropic.claude-3-haiku-20240307-v1:0"


def test_settings_reject_invalid_bedrock_backoff_relationship() -> None:
    with pytest.raises(ValueError, match="bedrock_backoff_max_ms must be >="):
        Settings(
            bedrock_backoff_base_ms=500,
            bedrock_backoff_max_ms=100,
        )
