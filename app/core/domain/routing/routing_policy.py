from __future__ import annotations

from typing import Protocol

from .routing_types import RoutingContext, RoutingDecision


class RoutingPolicy(Protocol):
    def decide(self, context: RoutingContext) -> RoutingDecision:
        ...
