from app.core.settings import settings
from app.core.utils.costs import estimate_cost


def test_estimate_cost_unknown_provider_returns_zero():
    assert estimate_cost("unknown", 1000, 1000) == 0.0


def test_estimate_cost_clamps_negative_tokens():
    assert estimate_cost("stub", -10, -20) == 0.0


def test_estimate_cost_uses_rates():
    # Arrange
    settings.cost_rates_by_provider["x"] = type("R", (), {"input_per_1k": 1.0, "output_per_1k": 2.0})()

    # Act / Assert: 1000 in + 500 out => 1*1.0 + 0.5*2.0 = 2.0
    assert estimate_cost("x", 1000, 500) == 2.0


# --- ORQ-37: the frozen snapshot and the generation-cost estimator ----------
#
# `estimate_cost` above is untouched: it has no production caller (only these
# tests), and its documented contract is to return 0.0 for anything unknown --
# the exact behaviour AC31 cannot use. The new estimator is a separate function
# so that contract stays intact.

import pytest

from app.core.utils.costs import (
    EMBEDDING_PRICE_SNAPSHOT,
    PRICE_SNAPSHOT,
    PRICE_SNAPSHOT_DATE,
    estimate_generation_cost_usd,
)


def test_openai_rate_is_applied_per_million_tokens():
    # gpt-4.1-mini: 0.40 in, 1.60 out, per 1M.
    # 1000 in  -> 0.001 * 0.40 = 0.00040
    #  500 out -> 0.0005 * 1.60 = 0.00080
    assert estimate_generation_cost_usd(
        provider="openai", model="gpt-4.1-mini", input_tokens=1000, output_tokens=500
    ) == pytest.approx(0.0012)


def test_bedrock_nemotron_rate_is_applied_per_million_tokens():
    # 0.06 in, 0.23 out: 0.00006 + 0.000115
    assert estimate_generation_cost_usd(
        provider="bedrock",
        model="nvidia.nemotron-nano-12b-v2",
        input_tokens=1000,
        output_tokens=500,
    ) == pytest.approx(0.000175)


def test_input_and_output_rates_are_not_swapped():
    """Asymmetric token counts, so swapping the two rates changes the result.

    With equal counts the two orderings agree, and the swap would survive.
    """
    only_input = estimate_generation_cost_usd(
        provider="openai", model="gpt-4.1-mini", input_tokens=1_000_000, output_tokens=0
    )
    only_output = estimate_generation_cost_usd(
        provider="openai", model="gpt-4.1-mini", input_tokens=0, output_tokens=1_000_000
    )
    assert only_input == pytest.approx(0.40)
    assert only_output == pytest.approx(1.60)


def test_the_divisor_is_per_million_not_per_thousand():
    """A per-1k divisor would report this as 400.0 instead of 0.40."""
    assert estimate_generation_cost_usd(
        provider="openai", model="gpt-4.1-mini", input_tokens=1_000_000, output_tokens=0
    ) == pytest.approx(0.40)


def test_an_unknown_model_on_a_known_provider_returns_none():
    """The case a provider-keyed table gets wrong: right provider, wrong model."""
    assert (
        estimate_generation_cost_usd(
            provider="openai", model="gpt-4o-mini", input_tokens=1000, output_tokens=500
        )
        is None
    )


def test_an_unknown_provider_returns_none():
    assert (
        estimate_generation_cost_usd(
            provider="anthropic", model="whatever", input_tokens=1000, output_tokens=500
        )
        is None
    )


def test_absent_token_counts_return_none_not_zero():
    """No usage reported means unknown cost, not free."""
    assert (
        estimate_generation_cost_usd(
            provider="openai", model="gpt-4.1-mini", input_tokens=None, output_tokens=5
        )
        is None
    )


def test_a_genuine_zero_is_zero_and_not_none():
    """The stub provider bills nothing. That is a measurement, not an absence.

    This is the distinction the whole design rests on: `None` means unpriced,
    `0.0` means priced at nothing. A falsy test anywhere downstream collapses
    them, which is the defect this pair of assertions exists to catch.
    """
    result = estimate_generation_cost_usd(
        provider="stub", model=None, input_tokens=1000, output_tokens=500
    )
    assert result == 0.0
    assert result is not None


def test_negative_token_counts_are_clamped():
    assert estimate_generation_cost_usd(
        provider="openai", model="gpt-4.1-mini", input_tokens=-10, output_tokens=-20
    ) == pytest.approx(0.0)


def test_the_snapshot_is_immutable():
    """AC31 quotes a FROZEN snapshot; a deployment or a test must not replace it."""
    with pytest.raises(TypeError):
        PRICE_SNAPSHOT[("openai", "gpt-4.1-mini")] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        EMBEDDING_PRICE_SNAPSHOT[("openai", "text-embedding-3-small")] = 0.0  # type: ignore[index]


def test_the_configured_openai_model_has_a_price():
    """If someone changes `openai_model` without adding a rate, cost silently
    becomes NULL for every request. Fail here instead."""
    assert ("openai", settings.openai_model) in PRICE_SNAPSHOT


def test_embedding_price_is_recorded_but_not_reachable_from_the_estimator():
    assert EMBEDDING_PRICE_SNAPSHOT[("openai", "text-embedding-3-small")] == 0.02
    assert (
        estimate_generation_cost_usd(
            provider="openai",
            model="text-embedding-3-small",
            input_tokens=1000,
            output_tokens=0,
        )
        is None
    )


def test_the_snapshot_is_dated():
    assert PRICE_SNAPSHOT_DATE == "2026-09-12"
