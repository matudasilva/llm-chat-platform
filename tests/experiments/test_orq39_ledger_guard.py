"""Hand-computed capacity and fail-closed input fixtures."""

from dataclasses import fields, replace
from decimal import Decimal, localcontext

import pytest

from experiments.conversational_semantic_memory.cost_bound import (
    CallLimits, CostBoundUnavailable, PoolMetadata, PricingSnapshot, compute_cost_bound,
)

D = Decimal
META = PoolMetadata(2, 3, 5, 20, 30, 2, 15, 90, 12)
LIMITS = CallLimits(100, 10, 50, 10, 20)
PRICES = PricingSnapshot(D("1"), D("2"), D("3"), D("4"), D("5"), "fixture", "2026-09-22")


def bound(metadata=META, limits=LIMITS, pricing=PRICES, **kwargs):
    return compute_cost_bound(metadata, limits, pricing, **({
        "task6_sub_cap": D("0.25"), "committed": D("0"),
        "unresolved_reservations": D("0"),
    } | kwargs))


def test_n_max_golden_fixture():
    result = bound()
    # Bytes: 100+4*10+20=160; 50+30+2*15=110; max(90,4*20)=90.
    assert (result.byte_bounds.generation, result.byte_bounds.extraction,
            result.byte_bounds.embedding) == (160, 110, 90)
    assert result.generation_cost == D("0.000180")
    assert result.extraction_cost == D("0.000410")
    assert result.embedding_cost == D("0.000450")
    # 2 languages * 2 attempts * (2*4*.00018 + 3*.00041 + 5*.00045).
    assert result.per_case_worst_case == D("0.01968")
    assert result.n_max == 12  # floor(.25/.01968)
    assert result.n_cap == 12
    assert bound(metadata=replace(META, capacity=4)).n_cap == 4
    assert bound(task6_sub_cap=D("1"), committed=D("9.8"),
                 unresolved_reservations=D("0.15")).n_max == 2


def test_embedding_output_cap_and_exact_budget_boundary():
    assert bound(metadata=replace(META, max_turn_bytes=1)).byte_bounds.embedding == 80
    with localcontext() as context:
        context.prec = 2
        assert bound(task6_sub_cap=D("0.03936")).n_max == 2
        assert bound(task6_sub_cap=D("0.0393599999999999999999")).n_max == 1


@pytest.mark.parametrize("record", [META, LIMITS, PRICES])
def test_every_missing_input_fails_closed(record):
    key = {PoolMetadata: "metadata", CallLimits: "limits", PricingSnapshot: "pricing"}[type(record)]
    for field in fields(record):
        with pytest.raises(CostBoundUnavailable, match="cost_bound_unavailable"):
            bound(**{key: replace(record, **{field.name: None})})
    with pytest.raises(CostBoundUnavailable):
        bound(**{key: None})


@pytest.mark.parametrize("key", ["task6_sub_cap", "committed", "unresolved_reservations"])
@pytest.mark.parametrize("value", [None, D("NaN"), D("Infinity"), D("-1"), 0.1])
def test_invalid_budget_inputs_fail_closed(key, value):
    with pytest.raises(CostBoundUnavailable):
        bound(**{key: value})


def test_exhausted_budget_and_invalid_counts():
    assert bound(task6_sub_cap=D(0)).n_max == 0
    with pytest.raises(CostBoundUnavailable):
        bound(committed=D(11))
    with pytest.raises(CostBoundUnavailable):
        bound(metadata=replace(META, steps_max=True))


def test_omitted_inputs_fail_closed():
    with pytest.raises(CostBoundUnavailable, match="cost_bound_unavailable"):
        compute_cost_bound()
    with pytest.raises(CostBoundUnavailable, match="task6_sub_cap"):
        compute_cost_bound(META, LIMITS, PRICES)
