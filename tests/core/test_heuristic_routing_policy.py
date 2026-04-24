import uuid

from app.core.domain.routing.heuristic_routing_policy import HeuristicRoutingPolicy
from app.core.domain.routing.routing_types import RoutingContext


def test_heuristic_routing_policy_routes_short_prompt_to_primary_cheap_tier() -> None:
    policy = HeuristicRoutingPolicy(
        primary_provider="openai",
        primary_model="gpt-4.1-mini",
        fallback_provider="bedrock",
        fallback_model="anthropic.claude-3-haiku-20240307-v1:0",
    )

    decision = policy.decide(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=14,
            estimated_tokens=4,
            primary_provider_available=True,
        )
    )

    assert decision.provider == "openai"
    assert decision.model_tier == "cheap"
    assert decision.rationale == "heuristic_message_length_cheap"


def test_heuristic_routing_policy_routes_high_estimated_tokens_to_fallback_smart_tier() -> None:
    policy = HeuristicRoutingPolicy(
        primary_provider="openai",
        primary_model="gpt-4.1-mini",
        fallback_provider="bedrock",
        fallback_model="anthropic.claude-3-haiku-20240307-v1:0",
    )

    decision = policy.decide(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=420,
            estimated_tokens=180,
            primary_provider_available=True,
        )
    )

    assert decision.provider == "bedrock"
    assert decision.fallback_provider == "openai"
    assert decision.model_tier == "smart"
    assert decision.rationale == "heuristic_estimated_tokens_smart"


def test_heuristic_routing_policy_routes_to_fallback_when_primary_is_unavailable() -> None:
    policy = HeuristicRoutingPolicy(
        primary_provider="openai",
        primary_model="gpt-4.1-mini",
        fallback_provider="bedrock",
        fallback_model="anthropic.claude-3-haiku-20240307-v1:0",
    )

    decision = policy.decide(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=32,
            estimated_tokens=8,
            primary_provider_available=False,
        )
    )

    assert decision.provider == "bedrock"
    assert decision.fallback_provider == "openai"
    assert decision.model_tier == "smart"
    assert decision.rationale == "heuristic_primary_unavailable"


def test_heuristic_routing_policy_keeps_streaming_on_safe_static_route() -> None:
    policy = HeuristicRoutingPolicy(
        primary_provider="openai",
        primary_model="gpt-4.1-mini",
        fallback_provider="bedrock",
        fallback_model="anthropic.claude-3-haiku-20240307-v1:0",
    )

    decision = policy.decide(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=True,
            message_length=21,
            estimated_tokens=6,
            primary_provider_available=True,
        )
    )

    assert decision.provider == "openai"
    assert decision.fallback_provider == "bedrock"
    assert decision.model_tier == "balanced"
    assert decision.rationale == "heuristic_stream_safe"
