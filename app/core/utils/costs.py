# app/core/utils/costs.py
from __future__ import annotations

from dataclasses import dataclass

from app.core.settings import settings


@dataclass(frozen=True)
class TokenRates:
    input_per_1k: float
    output_per_1k: float


def estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    """
    Provider-agnostic cost estimate based on token counts.

    Notes:
    - No external calls, no DB access.
    - Unknown providers return 0.0 (explicit MVP behavior).
    - Negative tokens are clamped to 0.
    """

    it = max(int(input_tokens or 0), 0)
    ot = max(int(output_tokens or 0), 0)

    rates = settings.cost_rates_by_provider.get(provider)
    if rates is None:
        return 0.0

    return (it / 1000.0) * rates.input_per_1k + (ot / 1000.0) * rates.output_per_1k
