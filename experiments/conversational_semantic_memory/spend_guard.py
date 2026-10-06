"""Reserve-before-dispatch spend guard and its hash-chained ledger (§Diseño 12).

A final total at or below the ceiling would not prove that a call which
*could* have exceeded it was never dispatched. So the order is inverted: the
worst-case cost of a call is reserved, fsynced and chain-linked **before** the
call happens, and the invariant checked at that moment is

    committed + unresolved reservations + proposed <= min(ceiling, sub-cap)

Committed means the provider's reported usage when it reports any, and the
full reservation when it does not: unknown usage never becomes zero, and a
reservation left unresolved by a crash stays charged until a usage record
resolves it. Dispatch is sequential (one call at a time), so there is never
more than one unresolved reservation in normal operation; the invariant is
written to hold regardless.

The ledger reuses the event log's chain format, so the same tamper evidence
applies: an edited or reordered ledger fails `verify`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from . import events

USD = Decimal


class SpendGuardError(RuntimeError):
    """Fail-closed: the call is not dispatched."""


@dataclass(frozen=True, slots=True)
class Pricing:
    """Per-million-token prices from the frozen snapshot."""

    model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal = Decimal(0)

    def cost(self, *, input_tokens: int, output_tokens: int = 0) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ) / Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Reservation:
    call_id: str
    usd: Decimal


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise SpendGuardError(f"cost_bound_unavailable: {field} is not a decimal string")
    try:
        return Decimal(value)
    except ArithmeticError as exc:
        raise SpendGuardError(f"cost_bound_unavailable: {field} is not a decimal") from exc


class SpendGuard:
    """One stage's guard. `sub_cap_usd` binds in addition to the ORQ ceiling."""

    def __init__(
        self,
        ledger_path: Path,
        *,
        stage: str,
        ceiling_usd: Decimal,
        sub_cap_usd: Decimal,
        pricing: Pricing,
    ) -> None:
        if sub_cap_usd <= 0 or ceiling_usd <= 0 or sub_cap_usd > ceiling_usd:
            raise SpendGuardError("cost_bound_unavailable: invalid caps")
        self.ledger_path = Path(ledger_path)
        self.stage = stage
        self.ceiling_usd = ceiling_usd
        self.sub_cap_usd = sub_cap_usd
        self.pricing = pricing

    # -- ledger state -----------------------------------------------------
    def _state(self) -> tuple[Decimal, Decimal, int]:
        """(committed, unresolved, next call ordinal) over the whole ledger."""
        committed = Decimal(0)
        reserved: dict[str, Decimal] = {}
        ordinal = 0
        for event in events.verify(self.ledger_path):
            payload = event.payload
            if event.type == "reservation":
                call_id = str(payload["call_id"])
                if call_id in reserved:
                    raise SpendGuardError("ledger inconsistent: duplicate reservation")
                reserved[call_id] = _decimal(payload["usd"], "reservation.usd")
                ordinal += 1
            elif event.type == "call_result":
                call_id = str(payload["call_id"])
                if call_id not in reserved:
                    raise SpendGuardError("ledger inconsistent: result without reservation")
                reservation = reserved.pop(call_id)
                usd = payload.get("usd")
                # No reported usage -> the reservation stands as the charge.
                committed += reservation if usd is None else _decimal(usd, "call_result.usd")
        return committed, sum(reserved.values(), Decimal(0)), ordinal

    def spent_usd(self) -> Decimal:
        committed, unresolved, _ = self._state()
        return committed + unresolved

    # -- dispatch protocol -------------------------------------------------
    def reserve(
        self,
        *,
        kind: str,
        max_input_tokens: int,
        max_output_tokens: int = 0,
        attempts: int = 2,
        payload_sha256: str,
        logical_attempt: str,
    ) -> Reservation:
        """Record the worst case, or refuse. Nothing is dispatched until this returns.

        `attempts` covers the one pre-registered transport retry: the worst
        case of a call that is retried once is two provider calls.
        """
        if max_input_tokens < 0 or max_output_tokens < 0 or attempts < 1:
            raise SpendGuardError("cost_bound_unavailable: invalid call bounds")
        proposed = self.pricing.cost(
            input_tokens=max_input_tokens, output_tokens=max_output_tokens
        ) * Decimal(attempts)
        committed, unresolved, ordinal = self._state()
        budget = min(self.ceiling_usd, self.sub_cap_usd)
        if committed + unresolved + proposed > budget:
            raise SpendGuardError(
                f"spend guard refused {kind}: committed {committed} + unresolved "
                f"{unresolved} + proposed {proposed} exceeds {budget}"
            )
        call_id = f"{self.stage}-{ordinal:06d}"
        events.append(
            self.ledger_path,
            "reservation",
            {
                "call_id": call_id,
                "stage": self.stage,
                "kind": kind,
                "logical_attempt": logical_attempt,
                "usd": str(proposed),
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "attempts": attempts,
                "payload_sha256": payload_sha256,
                "model": self.pricing.model,
            },
        )
        return Reservation(call_id=call_id, usd=proposed)

    def settle(
        self,
        reservation: Reservation,
        *,
        status: str,
        usage: Mapping[str, int] | None,
    ) -> Decimal:
        """Resolve a reservation with reported usage, or leave it charged in full."""
        if status not in {"ok", "failed"}:
            raise SpendGuardError("invalid call status")
        usd: str | None = None
        if usage is not None:
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
            output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                usd = str(
                    self.pricing.cost(input_tokens=input_tokens, output_tokens=output_tokens)
                )
        events.append(
            self.ledger_path,
            "call_result",
            {
                "call_id": reservation.call_id,
                "status": status,
                "usd": usd,
                "usage": dict(usage) if usage is not None else None,
            },
        )
        return Decimal(usd) if usd is not None else reservation.usd


def validate_ledger(
    ledger_path: Path, *, ceiling_usd: Decimal, sub_cap_usd: Decimal
) -> dict[str, object]:
    """Recompute the invariant for every dispatch in order (AC2).

    Replays the chain as it was written: at each reservation, everything
    already committed plus the reservations still open plus that reservation
    must have fitted the caps. A ledger that fails here is evidence that a
    call was dispatched it should not have been.
    """
    committed = Decimal(0)
    reserved: dict[str, Decimal] = {}
    rows: list[dict[str, object]] = []
    budget = min(ceiling_usd, sub_cap_usd)
    for event in events.verify(ledger_path):
        payload = event.payload
        if event.type == "reservation":
            proposed = _decimal(payload["usd"], "reservation.usd")
            open_total = sum(reserved.values(), Decimal(0))
            fits = committed + open_total + proposed <= budget
            rows.append(
                {
                    "call_id": payload["call_id"],
                    "committed_before": str(committed),
                    "unresolved_before": str(open_total),
                    "proposed": str(proposed),
                    "fits": fits,
                }
            )
            reserved[str(payload["call_id"])] = proposed
        elif event.type == "call_result":
            reservation = reserved.pop(str(payload["call_id"]))
            usd = payload.get("usd")
            committed += reservation if usd is None else _decimal(usd, "call_result.usd")
    total = committed + sum(reserved.values(), Decimal(0))
    return {
        "check": "spend_ledger",
        "passed": all(row["fits"] for row in rows) and total <= budget,
        "calls": len(rows),
        "total_usd": str(total),
        "budget_usd": str(budget),
        "rows": rows,
    }
