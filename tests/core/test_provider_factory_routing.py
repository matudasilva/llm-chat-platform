import uuid
import time
from types import SimpleNamespace

from app.core.domain import provider_factory as provider_factory_module
from app.core.domain.provider_factory import (
    build_provider_resolver,
    build_routing_policy,
)
from app.core.domain.routing.routing_policy import RoutingPolicy
from app.core.domain.routing.routing_types import RoutingContext, RoutingDecision
from app.core.providers.resilient_provider import ResilientProvider
from app.core.providers.stub_provider import StubProvider


def make_settings(**overrides):
    base = {
        "provider": "stub",
        "routing_policy": "static",
        "routing_shadow_policy": None,
        "routing_shadow_mode_enabled": False,
        "routing_shadow_timeout_ms": 25,
        "routing_message_length_cheap_max": 80,
        "routing_estimated_tokens_smart_min": 120,
        "provider_timeout_s": 30.0,
        "fallback_provider": None,
        "stub_provider_mode": "ok",
        "stub_simulated_latency_ms": 0,
        "openai_api_key": "test-key",
        "openai_model": "gpt-4.1-mini",
        "openai_max_attempts": 3,
        "openai_backoff_base_ms": 200,
        "openai_backoff_max_ms": 2000,
        "bedrock_region": "us-east-1",
        "bedrock_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "bedrock_prompt_version": "v1",
        "bedrock_max_attempts": 3,
        "bedrock_backoff_base_ms": 200,
        "bedrock_backoff_max_ms": 2000,
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "aws_session_token": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_routing_policy_returns_static_by_default() -> None:
    policy = build_routing_policy(make_settings())
    assert policy.__class__.__name__ == "StaticRoutingPolicy"


def test_build_routing_policy_returns_heuristic_when_enabled() -> None:
    policy = build_routing_policy(make_settings(routing_policy="heuristic"))
    assert policy.__class__.__name__ == "HeuristicRoutingPolicy"


def test_provider_resolver_keeps_zero_regression_with_static_policy(caplog) -> None:
    caplog.set_level("INFO")
    resolver = build_provider_resolver(
        make_settings(
            provider="stub",
            fallback_provider="openai",
        )
    )

    resolved = resolver(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=5,
            estimated_tokens=2,
            primary_provider_available=True,
        )
    )

    assert isinstance(resolved.provider, ResilientProvider)
    assert resolved.decision.provider == "stub"
    assert resolved.decision.fallback_provider == "openai"
    record = next(record for record in caplog.records if getattr(record, "event", None) == "routing.decision")
    assert record.policy_name == "static"
    assert record.provider == "stub"
    assert record.fallback_provider == "openai"
    assert record.message_length == 5
    assert record.estimated_tokens == 2
    assert record.primary_provider_available is True


def test_provider_resolver_can_build_direct_stub_provider() -> None:
    resolver = build_provider_resolver(make_settings(provider="stub", fallback_provider=None))

    resolved = resolver(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=5,
            estimated_tokens=2,
            primary_provider_available=True,
        )
    )

    assert isinstance(resolved.provider, StubProvider)
    assert resolved.decision.provider == "stub"


def test_provider_resolver_logs_shadow_divergence_without_affecting_active_provider(caplog) -> None:
    caplog.set_level("INFO")
    resolver = build_provider_resolver(
        make_settings(
            provider="stub",
            fallback_provider="openai",
            routing_policy="static",
            routing_shadow_mode_enabled=True,
            routing_shadow_policy="heuristic",
        )
    )

    resolved = resolver(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=400,
            estimated_tokens=160,
            primary_provider_available=True,
        )
    )

    assert isinstance(resolved.provider, ResilientProvider)
    assert resolved.decision.policy_name == "static"
    divergence_record = next(
        record for record in caplog.records if getattr(record, "event", None) == "routing.shadow_divergence"
    )
    assert divergence_record.active_policy_name == "static"
    assert divergence_record.shadow_policy_name == "heuristic"
    assert divergence_record.active_provider == "stub"
    assert divergence_record.shadow_provider == "openai"


def test_provider_resolver_discards_shadow_timeout(monkeypatch, caplog) -> None:
    caplog.set_level("INFO")

    class SlowShadowPolicy(RoutingPolicy):
        def decide(self, context: RoutingContext):
            time.sleep(0.01)
            return RoutingDecision(
                provider="openai",
                model="gpt-4.1-mini",
                model_tier="smart",
                rationale="shadow_slow",
                policy_name="heuristic",
            )

    monkeypatch.setattr(provider_factory_module, "_build_shadow_policy", lambda cfg: SlowShadowPolicy())
    resolver = build_provider_resolver(
        make_settings(
            provider="stub",
            routing_policy="static",
            routing_shadow_mode_enabled=True,
            routing_shadow_timeout_ms=1,
        )
    )

    resolved = resolver(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=5,
            estimated_tokens=2,
            primary_provider_available=True,
        )
    )

    assert isinstance(resolved.provider, StubProvider)
    timeout_record = next(record for record in caplog.records if getattr(record, "event", None) == "routing.shadow_timeout")
    assert timeout_record.shadow_timeout_ms == 1


def test_provider_resolver_swallows_shadow_errors(monkeypatch, caplog) -> None:
    caplog.set_level("INFO")

    class BrokenShadowPolicy(RoutingPolicy):
        def decide(self, context: RoutingContext):
            raise RuntimeError("shadow failed")

    monkeypatch.setattr(provider_factory_module, "_build_shadow_policy", lambda cfg: BrokenShadowPolicy())
    resolver = build_provider_resolver(
        make_settings(
            provider="stub",
            routing_policy="static",
            routing_shadow_mode_enabled=True,
        )
    )

    resolved = resolver(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=5,
            estimated_tokens=2,
            primary_provider_available=True,
        )
    )

    assert isinstance(resolved.provider, StubProvider)
    error_record = next(record for record in caplog.records if getattr(record, "event", None) == "routing.shadow_error")
    assert error_record.request_id
