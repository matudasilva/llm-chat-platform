# app/core/utils/costs.py
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from app.core.settings import settings


@dataclass(frozen=True)
class TokenRates:
    input_per_1k: float
    output_per_1k: float


# --- ORQ-37: the frozen price snapshot AC31's campaign cites ----------------
#
# A module constant, deliberately NOT a setting. AC31 requires a *frozen* price
# snapshot, and `settings.cost_rates_by_provider` is mutable at runtime -- the
# pre-existing `test_estimate_cost_uses_rates` writes into it. A snapshot a
# measurement campaign quotes must not be something a deployment or a test can
# silently replace, so it lives here behind a `MappingProxyType`.
#
# Keyed by `(provider, model)`, not by provider alone: a per-provider rate
# applies itself to whichever model happens to be configured, which is exactly
# how a confident wrong number gets produced.
#
# Rates are stored in the unit the sources publish -- USD per 1M tokens -- and
# converted once, in `estimate_generation_cost_usd`. Keeping the stored numbers
# identical to the published ones is what makes the snapshot auditable against
# its sources.

PRICE_SNAPSHOT_DATE = "2026-09-12"
PRICE_SNAPSHOT_UNIT = "usd_per_1m_tokens"


@dataclass(frozen=True)
class ModelRate:
    """Published rates for one `(provider, model)` pair, USD per 1M tokens."""

    input: float
    output: float
    # Recorded, deliberately UNUSED. `ProviderResult` exposes no cached-token
    # count, so there is nothing to apply it to; every observed input token is
    # charged at the full `input` rate, which cannot understate cost. Kept here
    # so the snapshot matches its published source and so wiring it later is a
    # change of code, not a re-derivation of prices.
    cached_input: float | None = None


PRICE_SNAPSHOT: MappingProxyType[tuple[str, str | None], ModelRate] = MappingProxyType(
    {
        ("openai", "gpt-4.1-mini"): ModelRate(input=0.40, cached_input=0.10, output=1.60),
        ("bedrock", "nvidia.nemotron-nano-12b-v2"): ModelRate(input=0.06, output=0.23),
        # The stub provider bills nothing. This is a real 0.0, not a missing
        # price: `estimate_generation_cost_usd` must return 0.0 here and None
        # for a pair it does not know.
        ("stub", None): ModelRate(input=0.0, output=0.0),
    }
)

# Recorded for completeness and NOT part of `estimated_cost_usd`, which is
# generation cost only (operator decision, 2026-09-12). Embedding calls happen
# inside the retrieval pipeline and never reach the metrics writer, and they do
# not differentiate Mode A from Mode B -- Mode B's ranking is lexical, and the
# documental channel is identical in both -- so including them would add a
# constant to both sides of Gate B2's comparison.
EMBEDDING_PRICE_SNAPSHOT: MappingProxyType[tuple[str, str], float] = MappingProxyType(
    {("openai", "text-embedding-3-small"): 0.02}
)


def estimate_generation_cost_usd(
    *,
    provider: str | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Generation cost for one request, or None when no price is known.

    **`None` and `0.0` are different answers and must stay different.** `None`
    means "this `(provider, model)` pair has no rate in the snapshot"; `0.0`
    means "priced, and it cost nothing" -- which is the true answer for the
    stub provider. Collapsing the first into the second is what would let a
    measurement campaign report zeros as if they were measured, and it is the
    reason `estimate_cost` above is left alone rather than extended: its
    documented contract is to return 0.0 for anything unknown.

    Token counts of `None` also yield `None`: a request whose provider reported
    no usage has an unknown cost, not a zero one. Negative counts are clamped,
    matching `estimate_cost`.
    """
    rate = PRICE_SNAPSHOT.get((provider or "", model))
    if rate is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None

    it = max(int(input_tokens), 0)
    ot = max(int(output_tokens), 0)
    return (it / 1_000_000.0) * rate.input + (ot / 1_000_000.0) * rate.output


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
