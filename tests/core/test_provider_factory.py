from types import SimpleNamespace

import pytest

from app.core.domain.disabled_provider import DisabledProvider
from app.core.providers.openai_provider import OpenAIProvider
from app.core.domain.provider_factory import build_provider
from app.core.providers.stub_provider import StubProvider


def make_settings(**overrides):
    base = {
        "provider": "stub",
        "provider_timeout_s": 30.0,
        "stub_provider_mode": "ok",
        "stub_simulated_latency_ms": 0,
        "openai_api_key": None,
        "openai_model": "gpt-4.1-mini",
        "openai_max_attempts": 3,
        "openai_backoff_base_ms": 200,
        "openai_backoff_max_ms": 2000,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_provider_returns_stub_provider() -> None:
    cfg = make_settings(
        provider="stub",
        stub_provider_mode="ok",
        stub_simulated_latency_ms=15,
    )

    provider = build_provider(cfg)

    assert isinstance(provider, StubProvider)
    assert provider.mode == "ok"
    assert provider.simulated_latency_ms == 15


def test_build_provider_returns_disabled_openai_when_api_key_missing() -> None:
    cfg = make_settings(
        provider="openai",
        openai_api_key=None,
    )

    provider = build_provider(cfg)

    assert isinstance(provider, DisabledProvider)


def test_build_provider_returns_openai_provider_when_config_is_complete() -> None:
    cfg = make_settings(
        provider="openai",
        openai_api_key="test-key",
        openai_model="gpt-4.1-mini",
        provider_timeout_s=12.0,
        openai_max_attempts=4,
        openai_backoff_base_ms=100,
        openai_backoff_max_ms=1500,
    )

    provider = build_provider(cfg)

    assert isinstance(provider, OpenAIProvider)


def test_build_provider_returns_disabled_provider_for_bedrock_placeholder() -> None:
    cfg = make_settings(provider="bedrock")

    provider = build_provider(cfg)

    assert isinstance(provider, DisabledProvider)


def test_build_provider_raises_for_unknown_provider() -> None:
    cfg = make_settings(provider="unknown-provider")

    with pytest.raises(ValueError, match="Unsupported provider"):
        build_provider(cfg)