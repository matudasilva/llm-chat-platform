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
