from __future__ import annotations

from .routing_types import RoutingContext, RoutingDecision


class StaticRoutingPolicy:
    def __init__(
        self,
        *,
        provider: str,
        model: str | None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model

    def decide(self, context: RoutingContext) -> RoutingDecision:
        return RoutingDecision(
            provider=self._provider,
            model=self._model,
            model_tier="balanced",
            rationale="static_default",
            fallback_provider=self._fallback_provider,
            fallback_model=self._fallback_model,
            policy_name="static",
            policy_version="v1",
        )
