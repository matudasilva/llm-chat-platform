import pytest

from app.core.settings import Settings


def test_settings_accept_valid_provider_config() -> None:
    settings = Settings(
        provider="stub",
        fallback_provider="openai",
        routing_policy="static",
        provider_timeout_s=30.0,
        stub_provider_mode="ok",
        stub_simulated_latency_ms=0,
        openai_max_attempts=3,
        openai_backoff_base_ms=200,
        openai_backoff_max_ms=2000,
    )

    assert settings.provider == "stub"
    assert settings.fallback_provider == "openai"
    assert settings.routing_policy == "static"
    assert settings.provider_timeout_s == 30.0


def test_settings_reject_invalid_provider() -> None:
    with pytest.raises(ValueError, match="provider must be one of"):
        Settings(provider="invalid-provider")


def test_settings_accept_primary_provider_alias() -> None:
    settings = Settings(PRIMARY_PROVIDER="bedrock")

    assert settings.provider == "bedrock"


def test_settings_primary_provider_alias_takes_precedence() -> None:
    settings = Settings(provider="stub", PRIMARY_PROVIDER="bedrock")

    assert settings.provider == "bedrock"


def test_settings_fallback_provider_alias_takes_precedence() -> None:
    settings = Settings(
        provider="stub",
        fallback_provider="openai",
        FALLBACK_PROVIDER="bedrock",
    )

    assert settings.provider == "stub"
    assert settings.fallback_provider == "bedrock"


def test_settings_fallback_provider_field_name_only() -> None:
    assert Settings(fallback_provider="openai").fallback_provider == "openai"


def test_settings_fallback_provider_alias_only() -> None:
    assert Settings(FALLBACK_PROVIDER="bedrock").fallback_provider == "bedrock"


def test_settings_primary_provider_field_name_only() -> None:
    assert Settings(provider="openai").provider == "openai"


def test_settings_primary_provider_alias_only() -> None:
    assert Settings(PRIMARY_PROVIDER="bedrock").provider == "bedrock"


def test_settings_provider_aliases_from_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "bedrock")
    monkeypatch.setenv("FALLBACK_PROVIDER", "openai")

    settings = Settings()

    assert settings.provider == "bedrock"
    assert settings.fallback_provider == "openai"


def test_settings_kwargs_take_precedence_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_PROVIDER", "bedrock")

    assert Settings(fallback_provider="openai").fallback_provider == "openai"


def test_settings_environment_takes_precedence_over_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("FALLBACK_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setenv("FALLBACK_PROVIDER", "bedrock")

    assert Settings(_env_file=tmp_path / ".env").fallback_provider == "bedrock"


def test_settings_unrelated_field_is_unchanged() -> None:
    assert Settings(routing_policy="heuristic").routing_policy == "heuristic"


def test_settings_default_routing_policy_is_static() -> None:
    settings = Settings()

    assert settings.routing_policy == "static"


def test_settings_accept_heuristic_routing_policy() -> None:
    settings = Settings(routing_policy="heuristic")

    assert settings.routing_policy == "heuristic"


def test_settings_accept_valid_shadow_routing_config() -> None:
    settings = Settings(
        routing_shadow_mode_enabled=True,
        routing_shadow_policy="heuristic",
        routing_shadow_timeout_ms=50,
        routing_message_length_cheap_max=64,
        routing_estimated_tokens_smart_min=160,
    )

    assert settings.routing_shadow_mode_enabled is True
    assert settings.routing_shadow_policy == "heuristic"
    assert settings.routing_shadow_timeout_ms == 50
    assert settings.routing_message_length_cheap_max == 64
    assert settings.routing_estimated_tokens_smart_min == 160


def test_settings_reject_invalid_routing_policy() -> None:
    with pytest.raises(ValueError, match="routing_policy must be one of"):
        Settings(routing_policy="ml")


def test_settings_reject_invalid_shadow_routing_policy() -> None:
    with pytest.raises(ValueError, match="routing_shadow_policy must be one of"):
        Settings(routing_shadow_policy="ml")


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
