from __future__ import annotations

from decimal import Decimal

import pytest

from experiments.conversational_semantic_memory import events
from experiments.conversational_semantic_memory.spend_guard import (
    Pricing,
    SpendGuard,
    SpendGuardError,
    validate_ledger,
)

PRICING = Pricing(model="text-embedding-3-small", input_usd_per_million=Decimal("0.02"))


def guard(tmp_path, *, ceiling="10", sub_cap="0.25") -> SpendGuard:
    return SpendGuard(
        tmp_path / "ledger.jsonl",
        stage="t3",
        ceiling_usd=Decimal(ceiling),
        sub_cap_usd=Decimal(sub_cap),
        pricing=PRICING,
    )


def reserve(g, tokens=1_000, attempts=2):
    return g.reserve(
        kind="embedding",
        max_input_tokens=tokens,
        attempts=attempts,
        payload_sha256="a" * 64,
        logical_attempt="unit",
    )


def test_reservation_prices_the_retry(tmp_path) -> None:
    g = guard(tmp_path)
    # 1_000 tokens at USD 0.02 per million = 0.00002, twice for the one retry.
    assert reserve(g).usd == Decimal("0.00004")


def test_reservation_precedes_the_call_in_the_ledger(tmp_path) -> None:
    g = guard(tmp_path)
    reservation = reserve(g)
    g.settle(reservation, status="ok", usage={"prompt_tokens": 10})
    chain = events.verify(g.ledger_path)
    assert [event.type for event in chain] == ["reservation", "call_result"]


def test_reported_usage_replaces_the_reservation(tmp_path) -> None:
    g = guard(tmp_path)
    g.settle(reserve(g), status="ok", usage={"prompt_tokens": 100})
    assert g.spent_usd() == PRICING.cost(input_tokens=100)


def test_missing_usage_stays_charged_at_the_reservation(tmp_path) -> None:
    g = guard(tmp_path)
    reservation = reserve(g)
    g.settle(reservation, status="ok", usage=None)
    assert g.spent_usd() == reservation.usd


def test_failed_call_is_still_charged(tmp_path) -> None:
    g = guard(tmp_path)
    reservation = reserve(g)
    g.settle(reservation, status="failed", usage=None)
    assert g.spent_usd() == reservation.usd


def test_unresolved_reservation_counts_against_the_budget(tmp_path) -> None:
    """A crash between reserve and settle must not free the money."""
    g = guard(tmp_path)
    reserve(g)  # never settled
    assert g.spent_usd() > 0
    fresh = guard(tmp_path)  # a new process reading the same ledger
    assert fresh.spent_usd() == g.spent_usd()


def test_guard_refuses_the_call_that_would_exceed_the_sub_cap(tmp_path) -> None:
    g = guard(tmp_path, sub_cap="0.00005")
    reserve(g)  # 0.00004 reserved
    with pytest.raises(SpendGuardError, match="exceeds"):
        reserve(g)
    # Refusal writes no reservation: the refused call cannot be dispatched.
    assert [event.type for event in events.verify(g.ledger_path)] == ["reservation"]


def test_sub_cap_binds_even_when_the_ceiling_would_allow_it(tmp_path) -> None:
    g = guard(tmp_path, ceiling="10", sub_cap="0.00001")
    with pytest.raises(SpendGuardError):
        reserve(g)


def test_invalid_caps_and_bounds_fail_closed(tmp_path) -> None:
    with pytest.raises(SpendGuardError):
        SpendGuard(
            tmp_path / "l.jsonl",
            stage="t3",
            ceiling_usd=Decimal("1"),
            sub_cap_usd=Decimal("2"),  # sub-cap above the ceiling
            pricing=PRICING,
        )
    with pytest.raises(SpendGuardError):
        reserve(guard(tmp_path), tokens=-1)


def test_tampered_ledger_fails_closed(tmp_path) -> None:
    g = guard(tmp_path)
    g.settle(reserve(g), status="ok", usage={"prompt_tokens": 100})
    text = g.ledger_path.read_text().replace('"usd":"0.000002"', '"usd":"0.0"')
    g.ledger_path.write_text(text)
    with pytest.raises(events.EventLogError):
        g.spent_usd()


def test_validate_ledger_replays_the_invariant_per_dispatch(tmp_path) -> None:
    g = guard(tmp_path)
    for _ in range(3):
        g.settle(reserve(g), status="ok", usage={"prompt_tokens": 100})
    report = validate_ledger(
        g.ledger_path, ceiling_usd=Decimal("10"), sub_cap_usd=Decimal("0.25")
    )
    assert report["passed"] is True
    assert report["calls"] == 3
    assert all(row["fits"] for row in report["rows"])


def test_validate_ledger_reports_a_dispatch_that_should_not_have_happened(tmp_path) -> None:
    g = guard(tmp_path)
    g.settle(reserve(g), status="ok", usage={"prompt_tokens": 100})
    # Same ledger judged against a cap it never fitted.
    report = validate_ledger(
        g.ledger_path, ceiling_usd=Decimal("10"), sub_cap_usd=Decimal("0.00001")
    )
    assert report["passed"] is False
