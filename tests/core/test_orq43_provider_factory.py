from uuid import uuid4

import pytest

from app.core.domain.disabled_provider import DisabledProvider
from app.core.domain.provider import ProviderInput
from app.core.domain.provider_factory import build_manual_provider_resolver, build_provider
from app.core.domain.routing.routing_types import RoutingContext
from app.core.providers.bedrock_provider import BedrockProvider
from app.core.providers.vertex_provider import VertexProvider
from app.core.settings import Settings


def context():
    return RoutingContext(request_id=uuid4(), stream=False, message_length=1,
                          estimated_tokens=1, primary_provider_available=True)


def test_manual_bedrock_uses_selected_model_and_location_without_default_model():
    cfg = Settings(bedrock_model=None, bedrock_region=None, fallback_provider="openai")
    result = build_manual_provider_resolver(
        cfg, provider="bedrock", model="selected-model", location="us-west-2", output_cap=100
    )(context())
    assert isinstance(result.provider.provider, BedrockProvider)
    assert result.provider.provider._cfg.model == "selected-model"
    assert result.provider.provider._cfg.region == "us-west-2"
    assert result.decision.policy_name == "manual"
    assert result.decision.rationale == "manual_selection"
    assert result.decision.fallback_provider is None
    assert result.decision.fallback_model is None
    assert result.evidence.fallback_used is False


def test_manual_vertex_is_gated_and_construction_keeps_adc_lazy(monkeypatch):
    cfg = Settings(vertex_project_id="project-123")
    args = dict(provider="vertex", model="gemini-test", location="us-central1", output_cap=123)
    with pytest.raises(ValueError, match="disabled"):
        build_manual_provider_resolver(cfg, **args)

    def fail_adc(*args, **kwargs):
        raise AssertionError("ADC must not be acquired during construction")

    monkeypatch.setattr("app.core.providers.google_adc.GoogleAdcAccessTokenProvider", fail_adc)
    result = build_manual_provider_resolver(cfg, vertex_enabled=True, **args)(context())
    assert isinstance(result.provider.provider, VertexProvider)
    assert result.provider.provider.cfg.max_output_tokens == 123
    assert result.provider.provider.cfg.location == "us-central1"
    assert result.provider.provider.token_provider is None
    assert result.decision.fallback_provider is None
    assert result.evidence.fallback_used is False


def test_generic_vertex_factory_remains_disabled():
    cfg = Settings().model_copy(update={"provider": "vertex"})
    assert isinstance(build_provider(cfg), DisabledProvider)


@pytest.mark.parametrize("overrides", [
    {"provider": "openai"}, {"model": ""}, {"location": ""},
    {"output_cap": 0}, {"output_cap": True},
])
def test_manual_resolver_rejects_invalid_selection(overrides):
    args = dict(provider="bedrock", model="selected", location="us-east-1", output_cap=10)
    args.update(overrides)
    with pytest.raises(ValueError):
        build_manual_provider_resolver(Settings(), **args)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["bedrock", "vertex"])
@pytest.mark.parametrize("requested, expected", [(None, 100), (200, 100), (25, 25)])
async def test_manual_cap_applies_to_generate_and_stream_without_owning_session(monkeypatch, provider, requested, expected):
    cfg = Settings(vertex_project_id="project-123")
    location = "us-central1" if provider == "vertex" else "us-east-1"
    resolved = build_manual_provider_resolver(
        cfg, provider=provider, model="selected", location=location,
        output_cap=100, vertex_enabled=True,
    )(context())
    seen = []
    session = object()

    async def generate(input):
        seen.append(input)
        return "result"

    async def stream(input):
        seen.append(input)
        return session

    monkeypatch.setattr(resolved.provider.provider, "generate", generate)
    monkeypatch.setattr(resolved.provider.provider, "stream", stream)
    original = ProviderInput(request_id=uuid4(), messages=[], max_tokens=requested)
    assert await resolved.provider.generate(original) == "result"
    assert await resolved.provider.stream(original) is session
    assert [item.max_tokens for item in seen] == [expected, expected]
    assert original.max_tokens == requested
    assert resolved.decision.fallback_provider is None
