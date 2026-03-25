from __future__ import annotations

from app.core.domain.provider import ProviderPort
from app.core.domain.disabled_provider import DisabledProvider
from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig
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
        if not cfg.bedrock_region:
            return DisabledProvider("bedrock", "BEDROCK_REGION missing")
        if not cfg.bedrock_model:
            return DisabledProvider("bedrock", "BEDROCK_MODEL missing")

        bedrock_cfg = BedrockProviderConfig(
            region=cfg.bedrock_region,
            model=cfg.bedrock_model,
            prompt_version=cfg.bedrock_prompt_version,
            timeout_s=cfg.provider_timeout_s,
            max_attempts=cfg.bedrock_max_attempts,
            backoff_base_ms=cfg.bedrock_backoff_base_ms,
            backoff_max_ms=cfg.bedrock_backoff_max_ms,
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            aws_session_token=cfg.aws_session_token,
        )
        return BedrockProvider(bedrock_cfg)

    raise ValueError(f"Unsupported provider: {provider}")
