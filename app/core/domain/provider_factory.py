from __future__ import annotations

from app.core.domain.provider import ProviderPort
from app.core.domain.disabled_provider import DisabledProvider
from app.core.providers.stub_provider import StubProvider
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig
from app.core.settings import settings


def build_provider(_settings=None) -> ProviderPort:
    cfg = _settings or settings
    provider = cfg.provider.lower()

    if provider == "stub":
        return StubProvider(
            mode=cfg.stub_provider_mode,
            simulated_latency_ms=cfg.stub_simulated_latency_ms,
        )

    if provider == "openai":
        if not cfg.openai_api_key:
            return DisabledProvider("openai", "OPENAI_API_KEY missing")

        openai_cfg = OpenAIProviderConfig(
            api_key=cfg.openai_api_key,
            model=cfg.openai_model,
            timeout_s=cfg.provider_timeout_s,
            max_attempts=cfg.openai_max_attempts,
            backoff_base_ms=cfg.openai_backoff_base_ms,
            backoff_max_ms=cfg.openai_backoff_max_ms,
        )
        return OpenAIProvider(openai_cfg)

    if provider == "bedrock":
        return DisabledProvider("bedrock", "not implemented yet")

    raise ValueError(f"Unsupported provider: {provider}")