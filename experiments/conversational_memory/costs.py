from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PriceTable:
    currency: str
    effective_date: str
    generation_model: str
    generation_input_per_million: float
    generation_output_per_million: float
    embedding_model: str
    embedding_input_per_million: float
    source_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StepCost:
    index_embedding_cost: float | None
    query_embedding_cost: float | None
    generation_api_cost: float | None
    rebuild_embedding_cost: float | None

    @property
    def embedding_api_cost(self) -> float | None:
        return nullable_sum((self.index_embedding_cost, self.query_embedding_cost))

    @property
    def step_total_estimated_api_cost(self) -> float | None:
        return nullable_sum(
            (
                self.index_embedding_cost,
                self.query_embedding_cost,
                self.generation_api_cost,
                self.rebuild_embedding_cost,
            )
        )


def generation_cost(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    prices: PriceTable,
) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    return (
        input_tokens * prices.generation_input_per_million
        + output_tokens * prices.generation_output_per_million
    ) / 1_000_000


def embedding_cost(*, tokens: int | None, prices: PriceTable) -> float | None:
    if tokens is None:
        return None
    return tokens * prices.embedding_input_per_million / 1_000_000


def nullable_sum(values: Iterable[float | None]) -> float | None:
    materialized = tuple(values)
    if any(value is None for value in materialized):
        return None
    return sum(value for value in materialized if value is not None)


def api_cost_per_correct_recall(
    *,
    total_cost: float | None,
    correct_recall_count: float,
) -> float | None | str:
    if total_cost is None:
        return None
    if correct_recall_count == 0:
        return "undefined"
    return total_cost / correct_recall_count
