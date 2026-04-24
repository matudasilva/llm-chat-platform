from __future__ import annotations

from .routing_types import RoutingContext, RoutingDecision
from .static_routing_policy import StaticRoutingPolicy


class HeuristicRoutingPolicy:
    def __init__(
        self,
        *,
        primary_provider: str,
        primary_model: str | None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
        message_length_cheap_max: int = 80,
        estimated_tokens_smart_min: int = 120,
    ) -> None:
        self._primary_provider = primary_provider
        self._primary_model = primary_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model
        self._message_length_cheap_max = message_length_cheap_max
        self._estimated_tokens_smart_min = estimated_tokens_smart_min
        self._static_policy = StaticRoutingPolicy(
            provider=primary_provider,
            model=primary_model,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )

    def decide(self, context: RoutingContext) -> RoutingDecision:
        if context.stream:
            static_decision = self._static_policy.decide(context)
            return RoutingDecision(
                provider=static_decision.provider,
                model=static_decision.model,
                model_tier=static_decision.model_tier,
                rationale="heuristic_stream_safe",
                fallback_provider=static_decision.fallback_provider,
                fallback_model=static_decision.fallback_model,
                policy_name="heuristic",
                policy_version="v1",
            )

        if not context.primary_provider_available and self._fallback_provider:
            return RoutingDecision(
                provider=self._fallback_provider,
                model=self._fallback_model,
                model_tier="smart",
                rationale="heuristic_primary_unavailable",
                fallback_provider=self._primary_provider,
                fallback_model=self._primary_model,
                policy_name="heuristic",
                policy_version="v1",
            )

        if self._is_cheap_prompt(context):
            return RoutingDecision(
                provider=self._primary_provider,
                model=self._primary_model,
                model_tier="cheap",
                rationale="heuristic_message_length_cheap",
                fallback_provider=self._fallback_provider,
                fallback_model=self._fallback_model,
                policy_name="heuristic",
                policy_version="v1",
            )

        if self._fallback_provider and self._is_smart_prompt(context):
            return RoutingDecision(
                provider=self._fallback_provider,
                model=self._fallback_model,
                model_tier="smart",
                rationale="heuristic_estimated_tokens_smart",
                fallback_provider=self._primary_provider,
                fallback_model=self._primary_model,
                policy_name="heuristic",
                policy_version="v1",
            )

        return RoutingDecision(
            provider=self._primary_provider,
            model=self._primary_model,
            model_tier="balanced",
            rationale="heuristic_default",
            fallback_provider=self._fallback_provider,
            fallback_model=self._fallback_model,
            policy_name="heuristic",
            policy_version="v1",
        )

    def _is_cheap_prompt(self, context: RoutingContext) -> bool:
        return context.message_length <= self._message_length_cheap_max

    def _is_smart_prompt(self, context: RoutingContext) -> bool:
        return context.estimated_tokens >= self._estimated_tokens_smart_min
