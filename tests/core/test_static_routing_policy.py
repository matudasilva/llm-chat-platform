import uuid

from app.core.domain.routing.routing_types import RoutingContext
from app.core.domain.routing.static_routing_policy import StaticRoutingPolicy


def test_static_routing_policy_returns_stable_decision() -> None:
    policy = StaticRoutingPolicy(
        provider="openai",
        model="gpt-4.1-mini",
        fallback_provider="bedrock",
        fallback_model="anthropic.claude-3-haiku-20240307-v1:0",
    )

    decision = policy.decide(
        RoutingContext(
            request_id=uuid.uuid4(),
            stream=False,
            message_length=5,
            estimated_tokens=2,
            primary_provider_available=True,
        )
    )

    assert decision.provider == "openai"
    assert decision.model == "gpt-4.1-mini"
    assert decision.model_tier == "balanced"
    assert decision.rationale == "static_default"
    assert decision.fallback_provider == "bedrock"
    assert decision.fallback_model == "anthropic.claude-3-haiku-20240307-v1:0"
    assert decision.policy_name == "static"
