from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence

from .dataset import AnswerExpectation, ConversationEvent, EvaluationStep
from .memory import RankedChunk, SemanticFact


@dataclass(frozen=True, slots=True)
class AnswerScore:
    conversational_recall_accuracy: float
    fact_consistency: float
    required_terms_found: int
    forbidden_terms_found: int


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    precision_at_k: float
    recall_at_k: float
    mrr: float
    delivered_unique_event_recall: float
    duplicate_chunk_slot_rate: float
    irrelevant_memory_injection_rate: float
    superseded_fact_retrieval_rate: float
    delivered_chunks: int
    delivered_unique_events: int


@dataclass(frozen=True, slots=True)
class SemanticExtractionScore:
    true_positive: int
    false_positive: int
    false_negative: int
    prohibited_extractions: int
    provenance_complete: int
    extracted_count: int

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return None if denominator == 0 else self.true_positive / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return None if denominator == 0 else self.true_positive / denominator

    @property
    def f1(self) -> float | None:
        precision = self.precision
        recall = self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)


def answer_score(answer: str, expected: AnswerExpectation) -> AnswerScore:
    normalized = normalize(answer)
    required = [normalize(term) for term in expected.required_terms]
    forbidden = [normalize(term) for term in expected.forbidden_terms]
    required_found = sum(bool(_spans(normalized, term)) for term in required)
    required_spans = [span for term in required for span in _spans(normalized, term)]
    forbidden_found = sum(
        any(
            not any(req_start <= start and end <= req_end for req_start, req_end in required_spans)
            for start, end in _spans(normalized, term)
        )
        for term in forbidden
    )
    recall = 1.0 if required_found == len(required) else 0.0
    consistency = 1.0 if recall == 1.0 and forbidden_found == 0 else 0.0
    return AnswerScore(recall, consistency, required_found, forbidden_found)


def retrieval_score(
    results: Sequence[RankedChunk],
    *,
    evaluation: EvaluationStep,
    evaluation_top_k_events: int,
) -> RetrievalScore:
    if evaluation_top_k_events <= 0:
        raise ValueError("evaluation_top_k_events must be positive")
    gold = set(evaluation.gold_source_event_ids)
    superseded = set(evaluation.superseded_source_event_ids)
    unique: list[str] = []
    for result in results:
        event_id = result.chunk.source_event_id
        if event_id not in unique:
            unique.append(event_id)
    evaluated = unique[:evaluation_top_k_events]
    relevant = sum(event_id in gold for event_id in evaluated)
    first = next((rank for rank, event_id in enumerate(evaluated, start=1) if event_id in gold), None)
    delivered_ids = {result.chunk.source_event_id for result in results}
    duplicate_slots = max(0, len(results) - len(delivered_ids))
    return RetrievalScore(
        precision_at_k=relevant / evaluation_top_k_events,
        recall_at_k=relevant / len(gold),
        mrr=0.0 if first is None else 1 / first,
        delivered_unique_event_recall=len(delivered_ids & gold) / len(gold),
        duplicate_chunk_slot_rate=0.0 if not results else duplicate_slots / len(results),
        irrelevant_memory_injection_rate=0.0 if not results else sum(result.chunk.source_event_id not in gold for result in results) / len(results),
        superseded_fact_retrieval_rate=0.0 if not results else sum(result.chunk.source_event_id in superseded for result in results) / len(results),
        delivered_chunks=len(results),
        delivered_unique_events=len(delivered_ids),
    )


def role_retrieval_score(
    results: Sequence[RankedChunk],
    *,
    evaluation: EvaluationStep,
    role: str,
    events_by_id: Mapping[str, ConversationEvent],
    evaluation_top_k_events: int,
) -> dict[str, float | int | None]:
    gold = {
        event_id
        for event_id in evaluation.gold_source_event_ids
        if role in {message.role for message in events_by_id[event_id].messages}
    }
    selected = [result for result in results if role in result.chunk.source_roles]
    if not gold:
        return {"precision_at_k": None, "recall_at_k": None, "mrr": None, "gold_events": 0, "selected_chunks": len(selected)}
    temporary = EvaluationStep(
        step_id=evaluation.step_id,
        query_event_id=evaluation.query_event_id,
        gold_source_event_ids=tuple(gold),
        gold_source_message_ids=evaluation.gold_source_message_ids,
        superseded_source_event_ids=(),
        fact_key=evaluation.fact_key,
        expected_value=evaluation.expected_value,
        effective_sequence=evaluation.effective_sequence,
        semantic_required=evaluation.semantic_required,
        fallback_required=evaluation.fallback_required,
        fallback_rationale=evaluation.fallback_rationale,
        b_answerable=evaluation.b_answerable,
        slices=evaluation.slices,
        expected=evaluation.expected,
    )
    score = retrieval_score(selected, evaluation=temporary, evaluation_top_k_events=evaluation_top_k_events)
    return {
        "precision_at_k": score.precision_at_k,
        "recall_at_k": score.recall_at_k,
        "mrr": score.mrr,
        "gold_events": len(gold),
        "selected_chunks": len(selected),
    }


def semantic_extraction_score(
    event: ConversationEvent,
    extracted: Sequence[SemanticFact],
) -> SemanticExtractionScore:
    eligible = {
        (fact.fact_key, normalize(fact.value), fact.source_role)
        for fact in event.gold_facts
        if fact.eligible and not fact.prohibited
    }
    prohibited = {
        (fact.fact_key, normalize(fact.value))
        for fact in event.gold_facts
        if fact.prohibited
    }
    observed = {
        (fact.fact_key, normalize(fact.value), fact.source_role)
        for fact in extracted
    }
    true_positive = len(observed & eligible)
    false_positive = len(observed - eligible)
    prohibited_extractions = sum((fact.fact_key, normalize(fact.value)) in prohibited for fact in extracted)
    provenance_complete = sum(
        fact.source_event_id == event.event_id
        and bool(fact.source_message_ids)
        and bool(fact.tenant_id)
        and bool(fact.conversation_id)
        for fact in extracted
    )
    return SemanticExtractionScore(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=len(eligible - observed),
        prohibited_extractions=prohibited_extractions,
        provenance_complete=provenance_complete,
        extracted_count=len(extracted),
    )


def fallback_confusion(decisions: Sequence[tuple[bool, bool]]) -> dict[str, int | float | None]:
    true_positive = sum(actual and expected for actual, expected in decisions)
    false_positive = sum(actual and not expected for actual, expected in decisions)
    false_negative = sum(not actual and expected for actual, expected in decisions)
    true_negative = sum(not actual and not expected for actual, expected in decisions)
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": None if precision_denominator == 0 else true_positive / precision_denominator,
        "recall": None if recall_denominator == 0 else true_positive / recall_denominator,
        "activation_rate": None if not decisions else (true_positive + false_positive) / len(decisions),
    }


def echo_overlap(answer: str, historical_assistant: Sequence[str], memory_texts: Sequence[str]) -> float:
    answer_ngrams = _ngrams(answer, 3)
    if not answer_ngrams:
        return 0.0
    scores = []
    for text in (*historical_assistant, *memory_texts):
        other = _ngrams(text, 3)
        if other:
            scores.append(len(answer_ngrams & other) / len(answer_ngrams | other))
    return max(scores, default=0.0)


def aggregate(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "mean": mean(values) if values else None,
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
    }


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _spans(value: str, term: str) -> list[tuple[int, int]]:
    if not term:
        return []
    return [(match.start(), match.end()) for match in re.finditer(re.escape(term), value)]


def _ngrams(value: str, size: int) -> set[tuple[str, ...]]:
    words = re.findall(r"[\w$.-]+", normalize(value), flags=re.UNICODE)
    return {tuple(words[index:index + size]) for index in range(len(words) - size + 1)}
