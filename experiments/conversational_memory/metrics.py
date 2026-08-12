from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence

from .dataset import AnswerExpectation
from .memory import RetrievedChunk


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    precision_at_k: float
    recall_at_k: float
    mrr: float
    delivered_unique_source_recall: float
    duplicate_chunk_slot_rate: float
    irrelevant_memory_injection_rate: float
    superseded_fact_retrieval_rate: float
    unique_source_count: int
    delivered_chunk_count: int


@dataclass(frozen=True, slots=True)
class AnswerMetrics:
    conversational_recall_accuracy: float
    fact_consistency: float
    required_terms_found: int
    forbidden_terms_found: int


def ranking_metrics(
    results: Sequence[RetrievedChunk],
    *,
    gold_source_message_ids: Sequence[str],
    superseded_source_message_ids: Sequence[str],
    evaluation_top_k_messages: int,
) -> RankingMetrics:
    if evaluation_top_k_messages <= 0:
        raise ValueError("evaluation_top_k_messages must be positive")
    gold = set(gold_source_message_ids)
    if not gold:
        raise ValueError("retrieval metrics are undefined without gold messages")
    superseded = set(superseded_source_message_ids)
    unique = collapse_source_messages(results)
    evaluated = unique[:evaluation_top_k_messages]
    relevant_count = sum(source_id in gold for source_id in evaluated)
    first_relevant = next(
        (rank for rank, source_id in enumerate(evaluated, start=1) if source_id in gold),
        None,
    )
    delivered_ids = {result.chunk.source_message_id for result in results}
    duplicate_slots = max(0, len(results) - len(delivered_ids))
    irrelevant_chunks = sum(result.chunk.source_message_id not in gold for result in results)
    superseded_chunks = sum(result.chunk.source_message_id in superseded for result in results)
    delivered_count = len(results)
    return RankingMetrics(
        precision_at_k=relevant_count / evaluation_top_k_messages,
        recall_at_k=relevant_count / len(gold),
        mrr=0.0 if first_relevant is None else 1.0 / first_relevant,
        delivered_unique_source_recall=len(delivered_ids & gold) / len(gold),
        duplicate_chunk_slot_rate=0.0 if not delivered_count else duplicate_slots / delivered_count,
        irrelevant_memory_injection_rate=0.0 if not delivered_count else irrelevant_chunks / delivered_count,
        superseded_fact_retrieval_rate=0.0 if not delivered_count else superseded_chunks / delivered_count,
        unique_source_count=len(unique),
        delivered_chunk_count=delivered_count,
    )


def role_ranking_metrics(
    results: Sequence[RetrievedChunk],
    *,
    gold_source_message_ids: Sequence[str],
    source_roles: Mapping[str, str],
    role: str,
    evaluation_top_k_messages: int,
) -> dict[str, float | int | None]:
    role_gold = {source_id for source_id in gold_source_message_ids if source_roles[source_id] == role}
    role_results = [result for result in results if result.chunk.source_role == role]
    if not role_gold:
        return {
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "gold_count": 0,
            "selected_chunks": len(role_results),
        }
    metric = ranking_metrics(
        role_results,
        gold_source_message_ids=tuple(role_gold),
        superseded_source_message_ids=(),
        evaluation_top_k_messages=evaluation_top_k_messages,
    )
    return {
        "precision_at_k": metric.precision_at_k,
        "recall_at_k": metric.recall_at_k,
        "mrr": metric.mrr,
        "gold_count": len(role_gold),
        "selected_chunks": len(role_results),
    }


def collapse_source_messages(results: Sequence[RetrievedChunk]) -> list[str]:
    seen: set[str] = set()
    collapsed: list[str] = []
    for result in results:
        source_id = result.chunk.source_message_id
        if source_id not in seen:
            seen.add(source_id)
            collapsed.append(source_id)
    return collapsed


def answer_metrics(answer: str, expected: AnswerExpectation) -> AnswerMetrics:
    normalized = normalize_for_scoring(answer)
    required = [normalize_for_scoring(term) for term in expected.required_terms]
    forbidden = [normalize_for_scoring(term) for term in expected.forbidden_terms]
    required_found = sum(term in normalized for term in required)
    required_spans = [
        span
        for term in required
        for span in _occurrence_spans(normalized, term)
    ]
    forbidden_found = sum(
        any(
            not any(
                required_start <= forbidden_start and forbidden_end <= required_end
                for required_start, required_end in required_spans
            )
            for forbidden_start, forbidden_end in _occurrence_spans(normalized, term)
        )
        for term in forbidden
    )
    recall = 1.0 if required_found == len(required) else 0.0
    consistent = 1.0 if recall == 1.0 and forbidden_found == 0 else 0.0
    return AnswerMetrics(recall, consistent, required_found, forbidden_found)


def echo_overlap(
    answer: str,
    historical_assistant_messages: Sequence[str],
    memory_chunks: Sequence[str],
) -> float:
    answer_ngrams = _word_ngrams(answer, 3)
    if not answer_ngrams:
        return 0.0
    comparisons = [*historical_assistant_messages, *memory_chunks]
    scores = []
    for text in comparisons:
        other = _word_ngrams(text, 3)
        if other:
            scores.append(len(answer_ngrams & other) / len(answer_ngrams | other))
    return max(scores, default=0.0)


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def aggregate(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "mean": mean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
    }


def normalize_for_scoring(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _occurrence_spans(value: str, term: str) -> list[tuple[int, int]]:
    if not term:
        return []
    return [(match.start(), match.end()) for match in re.finditer(re.escape(term), value)]


def _word_ngrams(value: str, size: int) -> set[tuple[str, ...]]:
    words = re.findall(r"[\w$.-]+", normalize_for_scoring(value), flags=re.UNICODE)
    return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}
