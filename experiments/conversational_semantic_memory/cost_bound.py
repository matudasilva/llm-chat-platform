"""Tokenizer-free, conservative T6 capacity from explicit frozen input data."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal, localcontext
from fractions import Fraction


class CostBoundUnavailable(ValueError):
    """A missing or invalid bound must stop capacity planning."""

    reason = "cost_bound_unavailable"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.reason}: {detail}")


@dataclass(frozen=True, slots=True)
class PoolMetadata:
    steps_max: int
    user_turns_max: int
    embedding_calls_max: int
    max_current_message_bytes: int
    max_user_turn_bytes: int
    max_slots_per_conversation: int
    max_serialized_slot_entry_bytes: int
    max_turn_bytes: int
    capacity: int


@dataclass(frozen=True, slots=True)
class CallLimits:
    system_envelope_bytes: int
    added_context_cap_chars: int
    extraction_template_bytes: int
    generation_max_tokens: int
    extraction_max_tokens: int


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    generation_input_per_million: Decimal
    generation_output_per_million: Decimal
    extraction_input_per_million: Decimal
    extraction_output_per_million: Decimal
    embedding_input_per_million: Decimal
    source: str
    retrieved_on: str


@dataclass(frozen=True, slots=True)
class ByteBounds:
    generation: int
    extraction: int
    embedding: int


@dataclass(frozen=True, slots=True)
class CostBound:
    byte_bounds: ByteBounds
    generation_cost: Decimal
    extraction_cost: Decimal
    embedding_cost: Decimal
    per_case_worst_case: Decimal
    budget: Decimal
    n_max: int
    n_cap: int


def _integers(record: object, expected: type) -> None:
    if not isinstance(record, expected):
        raise CostBoundUnavailable(f"missing {expected.__name__}")
    for field in fields(record):
        value = getattr(record, field.name)
        if type(value) is not int or value < 0:
            raise CostBoundUnavailable(f"invalid {field.name}")


def _money(value: Decimal, name: str) -> Fraction:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise CostBoundUnavailable(f"missing or invalid {name}")
    return Fraction(value)


def _decimal(value: Fraction) -> Decimal:
    # All denominators arise from finite Decimal inputs and division by 10**6.
    # Enough precision for an exact conversion, independent of caller context.
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def byte_bounds(metadata: PoolMetadata, limits: CallLimits) -> ByteBounds:
    """Slot-entry sizes must include their serialization separators/container share."""
    _integers(metadata, PoolMetadata)
    _integers(limits, CallLimits)
    if limits.generation_max_tokens == 0 or limits.extraction_max_tokens == 0:
        raise CostBoundUnavailable("output token caps must be positive")
    return ByteBounds(
        limits.system_envelope_bytes + 4 * limits.added_context_cap_chars
        + metadata.max_current_message_bytes,
        limits.extraction_template_bytes + metadata.max_user_turn_bytes
        + metadata.max_slots_per_conversation * metadata.max_serialized_slot_entry_bytes,
        max(metadata.max_turn_bytes, 4 * limits.extraction_max_tokens),
    )


def compute_cost_bound(metadata: PoolMetadata | None = None,
                       limits: CallLimits | None = None,
                       pricing: PricingSnapshot | None = None, *,
                       task6_sub_cap: Decimal | None = None,
                       committed: Decimal | None = None,
                       unresolved_reservations: Decimal | None = None) -> CostBound:
    """Charge two languages, four generation arms, and two attempts per call.

    Exact rational arithmetic prevents Decimal context rounding from increasing
    the affordable case count. USD 10 is the design ceiling, not a live price.
    """
    bounds = byte_bounds(metadata, limits)
    if not isinstance(pricing, PricingSnapshot) or not pricing.source or not pricing.retrieved_on:
        raise CostBoundUnavailable("missing pricing snapshot provenance")
    prices = [_money(getattr(pricing, field.name), field.name)
              for field in fields(pricing) if field.name.endswith("per_million")]
    gi, go, ei, eo, emb = prices
    generation = (bounds.generation * gi + limits.generation_max_tokens * go) / 1_000_000
    extraction = (bounds.extraction * ei + limits.extraction_max_tokens * eo) / 1_000_000
    embedding = bounds.embedding * emb / 1_000_000
    per_case = 4 * (metadata.steps_max * 4 * generation
                    + metadata.user_turns_max * extraction
                    + metadata.embedding_calls_max * embedding)
    budget = min(_money(task6_sub_cap, "task6_sub_cap"), Fraction(10)
                 - _money(committed, "committed")
                 - _money(unresolved_reservations, "unresolved_reservations"))
    if budget < 0 or per_case <= 0:
        raise CostBoundUnavailable("negative remaining budget or non-positive case cost")
    n_max = budget // per_case
    return CostBound(bounds, _decimal(generation), _decimal(extraction), _decimal(embedding),
                     _decimal(per_case), _decimal(budget), n_max, min(n_max, metadata.capacity))
