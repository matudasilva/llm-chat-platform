from __future__ import annotations

import os

from app.core.domain.provider import ProviderPort
from app.core.domain.disabled_provider import DisabledProvider
from app.core.providers.stub_provider import StubProvider
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig

def build_provider(_settings=None) -> ProviderPort:
    provider = os.getenv("PROVIDER", "stub").lower()

    if provider == "stub":
        mode = os.getenv("STUB_PROVIDER_MODE", "ok")
        latency_ms = int(os.getenv("STUB_SIMULATED_LATENCY_MS", "0"))
        return StubProvider(mode=mode, simulated_latency_ms=latency_ms)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return DisabledProvider("openai", "OPENAI_API_KEY missing")
    
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        timeout_s = float(os.getenv("PROVIDER_TIMEOUT_S", "12.0"))

        cfg = OpenAIProviderConfig(api_key=api_key, model=model, timeout_s=timeout_s)
        return OpenAIProvider(cfg)

    if provider == "bedrock":
        return DisabledProvider("bedrock", "not implemented yet")

    return DisabledProvider(provider, "unknown provider")