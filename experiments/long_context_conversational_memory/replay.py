"""Teacher-forced replay, scoped BM25, and whole-event context packing."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable, Sequence

from .model import EvaluationStep, EvaluationStepAudit, Event, NONCE_PATTERN
from .tokenization import Encoding, canonical_event_text, event_token_count, token_count

B_HISTORY_TOKEN_BUDGET = 4_096
FIXED_OVERHEAD_TOKEN_CAP = 512
E_RECENT_TOKEN_BUDGET = 1_024
E_RETRIEVED_TOKEN_BUDGET = 3_072
BM25_QUERY_TOKEN_CAP = 256
BM25_TOP_K = 5
BM25_K1 = 1.2
BM25_B = 0.75
_LEXICAL_TOKEN = re.compile(r"(?u)[^\W_]+")
_NONCE_IN_TEXT = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{0,63}(?![A-Za-z0-9_])",
    flags=re.ASCII,
)


class ReplayIntegrityError(RuntimeError):
    """A replay or scope invariant failed closed."""


class IsolationViolation(ReplayIntegrityError):
    """A tenant, conversation, or registered canary crossed its boundary."""


@dataclass(frozen=True, slots=True)
class EventSelection:
    included: tuple[Event, ...]
    excluded: tuple[Event, ...]
    used_tokens: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class RankedEvent:
    event: Event
    score: float


@dataclass(frozen=True, slots=True)
class ScopeAudit:
    shared_prefilter_corpus_count: int
    wrong_tenant_prefilter_count: int
    wrong_conversation_prefilter_count: int
    postfilter_candidate_count: int
    wrong_tenant_canary_event_id: str
    wrong_conversation_canary_event_id: str
    canaries_absent_postfilter: bool


@dataclass(frozen=True, slots=True)
class PackedContext:
    arm_id: str
    delivered_events: tuple[Event, ...]
    historical_tokens: int
    overhead_tokens: int
    prompt_text: str
    recent_event_ids: tuple[str, ...] = ()
    retrieved_event_ids: tuple[str, ...] = ()

    @property
    def total_input_tokens(self) -> int:
        return self.historical_tokens + self.overhead_tokens


@dataclass(frozen=True, slots=True)
class PromptFraming:
    """Fixed framing pieces that always render the authoritative current question."""

    system_and_fixed_prefix: str
    current_question_prefix: str
    current_question_suffix: str

    def render(self, current_question: str) -> str:
        if not all(
            isinstance(value, str)
            for value in (
                self.system_and_fixed_prefix,
                self.current_question_prefix,
                self.current_question_suffix,
                current_question,
            )
        ):
            raise TypeError("prompt framing fields must be text")
        return (
            self.system_and_fixed_prefix
            + self.current_question_prefix
            + current_question
            + self.current_question_suffix
        )


@dataclass(frozen=True, slots=True)
class IsolationChallenge:
    wrong_tenant_canary_event_id: str
    wrong_tenant_sentinel_nonce: str
    wrong_conversation_canary_event_id: str
    wrong_conversation_sentinel_nonce: str

    def __post_init__(self) -> None:
        if self.wrong_tenant_canary_event_id == self.wrong_conversation_canary_event_id:
            raise ValueError("isolation canary event IDs must be distinct")
        sentinels = (
            self.wrong_tenant_sentinel_nonce,
            self.wrong_conversation_sentinel_nonce,
        )
        if sentinels[0] == sentinels[1]:
            raise ValueError("isolation sentinel nonces must be distinct")
        if any(NONCE_PATTERN.fullmatch(nonce) is None for nonce in sentinels):
            raise ValueError("isolation sentinels must satisfy the frozen nonce regex")


def authoritative_prefix(step: EvaluationStep) -> tuple[Event, ...]:
    """Return the immutable, confirmed, chronologically ordered source prefix."""

    events = step.authoritative_events
    if any(not event.confirmed for event in events):
        raise ReplayIntegrityError("candidate or unconfirmed event entered replay")
    return events


def _select_recent_complete_suffix(
    events: Sequence[Event], encoding: Encoding, budget: int
) -> EventSelection:
    if budget < 0:
        raise ValueError("budget must be non-negative")
    accepted_newest_first: list[Event] = []
    used = 0
    for event in reversed(events):
        size = event_token_count(encoding, event)
        if size > budget - used:
            break
        accepted_newest_first.append(event)
        used += size
    included = tuple(reversed(accepted_newest_first))
    included_ids = {event.event_id for event in included}
    excluded = tuple(event for event in events if event.event_id not in included_ids)
    return EventSelection(
        included=included,
        excluded=excluded,
        used_tokens=used,
        truncated=bool(excluded),
    )


def _validate_framing(encoding: Encoding, framing_text: str) -> int:
    overhead = token_count(encoding, framing_text)
    if overhead > FIXED_OVERHEAD_TOKEN_CAP:
        raise ReplayIntegrityError("fixed framing exceeds its 512-token allowance")
    return overhead


def build_bounded_history(
    step: EvaluationStep, encoding: Encoding, framing: PromptFraming
) -> tuple[PackedContext, EventSelection]:
    """Build B as the newest complete-event suffix, stopping at the first gap."""

    events = authoritative_prefix(step)
    selection = _select_recent_complete_suffix(
        events, encoding, B_HISTORY_TOKEN_BUDGET
    )
    framing_text = framing.render(step.current_question)
    overhead = _validate_framing(encoding, framing_text)
    history = "".join(canonical_event_text(event) for event in selection.included)
    packed = PackedContext(
        arm_id="B",
        delivered_events=selection.included,
        historical_tokens=selection.used_tokens,
        overhead_tokens=overhead,
        prompt_text=history + framing_text,
        recent_event_ids=tuple(event.event_id for event in selection.included),
    )
    if packed.total_input_tokens > 4_608:
        raise ReplayIntegrityError("B exceeds its maximum input budget")
    return packed, selection


def lexical_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(_LEXICAL_TOKEN.findall(normalized))


def contextual_query_tokens(step: EvaluationStep) -> tuple[str, ...]:
    """Use the current question's first-occurrence lexical tokens, capped at 256."""

    unique_tokens: list[str] = []
    seen: set[str] = set()
    for token in lexical_tokens(step.current_question):
        if token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return tuple(unique_tokens[:BM25_QUERY_TOKEN_CAP])


def filter_event_scope(
    events: Iterable[Event], tenant_id: str, conversation_id: str
) -> tuple[Event, ...]:
    return tuple(
        event
        for event in events
        if event.confirmed
        and event.tenant_id == tenant_id
        and event.conversation_id == conversation_id
    )


def validate_isolation_challenge(
    shared_events: Sequence[Event],
    *,
    tenant_id: str,
    conversation_id: str,
    challenge: IsolationChallenge,
    current_question: str,
    authoritative_events: Sequence[Event],
    delivered_events: Sequence[Event] = (),
) -> ScopeAudit:
    """Require effective canaries and prove filtering/delivery exclusion."""

    by_id = {event.event_id: event for event in shared_events}
    if len(by_id) != len(shared_events):
        raise ReplayIntegrityError("shared retrieval corpus contains duplicate event IDs")
    try:
        wrong_tenant = by_id[challenge.wrong_tenant_canary_event_id]
        wrong_conversation = by_id[challenge.wrong_conversation_canary_event_id]
    except KeyError as exc:
        raise ReplayIntegrityError("registered isolation canary is absent") from exc
    if wrong_tenant.tenant_id == tenant_id:
        raise ReplayIntegrityError("wrong-tenant canary is not outside the tenant")
    if not (
        wrong_conversation.tenant_id == tenant_id
        and wrong_conversation.conversation_id != conversation_id
    ):
        raise ReplayIntegrityError(
            "wrong-conversation canary is not in the required competing scope"
        )
    if not wrong_tenant.confirmed or not wrong_conversation.confirmed:
        raise ReplayIntegrityError("isolation canaries must be confirmed events")
    authoritative_ids = {event.event_id for event in authoritative_events}
    if {
        challenge.wrong_tenant_canary_event_id,
        challenge.wrong_conversation_canary_event_id,
    } & authoritative_ids:
        raise ReplayIntegrityError("isolation canary entered the authoritative prefix")
    authoritative_text = "\n".join(event.document_text() for event in authoritative_events)
    authoritative_nonces = set(_NONCE_IN_TEXT.findall(authoritative_text))
    challenge_sentinels = {
        challenge.wrong_tenant_sentinel_nonce,
        challenge.wrong_conversation_sentinel_nonce,
    }
    if challenge_sentinels & authoritative_nonces:
        raise ReplayIntegrityError("isolation sentinel entered the authoritative prefix")
    reusable_question = _NONCE_IN_TEXT.sub(" ", current_question)
    required_question_terms = set(lexical_tokens(reusable_question))
    if not required_question_terms:
        raise ReplayIntegrityError(
            "isolation challenge requires reusable non-nonce query terms"
        )
    for canary, sentinel in (
        (wrong_tenant, challenge.wrong_tenant_sentinel_nonce),
        (wrong_conversation, challenge.wrong_conversation_sentinel_nonce),
    ):
        if sentinel not in set(_NONCE_IN_TEXT.findall(canary.document_text())):
            raise ReplayIntegrityError("isolation canary is missing its sentinel nonce")
        if not required_question_terms.issubset(
            set(lexical_tokens(canary.document_text()))
        ):
            raise ReplayIntegrityError(
                "isolation canary does not reuse every non-nonce query term"
            )

    scoped = filter_event_scope(shared_events, tenant_id, conversation_id)
    canary_ids = {
        challenge.wrong_tenant_canary_event_id,
        challenge.wrong_conversation_canary_event_id,
    }
    postfilter_ids = {event.event_id for event in scoped}
    delivered_ids = {event.event_id for event in delivered_events}
    for event in delivered_events:
        if (event.tenant_id, event.conversation_id) != (tenant_id, conversation_id):
            raise IsolationViolation("cross-scope event reached context delivery")
    if canary_ids & delivered_ids:
        raise IsolationViolation("registered isolation canary reached delivery")
    canaries_absent = not bool(canary_ids & postfilter_ids)
    if not canaries_absent:
        raise IsolationViolation("registered isolation canary survived scope filtering")

    return ScopeAudit(
        shared_prefilter_corpus_count=len(shared_events),
        wrong_tenant_prefilter_count=sum(
            event.tenant_id != tenant_id for event in shared_events
        ),
        wrong_conversation_prefilter_count=sum(
            event.tenant_id == tenant_id
            and event.conversation_id != conversation_id
            for event in shared_events
        ),
        postfilter_candidate_count=len(scoped),
        wrong_tenant_canary_event_id=challenge.wrong_tenant_canary_event_id,
        wrong_conversation_canary_event_id=challenge.wrong_conversation_canary_event_id,
        canaries_absent_postfilter=canaries_absent,
    )


def rank_bm25(
    shared_events: Sequence[Event],
    query_tokens: Sequence[str],
    *,
    tenant_id: str,
    conversation_id: str,
) -> tuple[RankedEvent, ...]:
    """Rank a locally scoped event index using the exact registered BM25."""

    documents = filter_event_scope(shared_events, tenant_id, conversation_id)
    if not documents:
        return ()
    document_tokens = {
        event.event_id: lexical_tokens(event.document_text()) for event in documents
    }
    average_length = sum(map(len, document_tokens.values())) / len(documents)
    if average_length == 0:
        raise ReplayIntegrityError("BM25 average document length is zero")
    document_frequency = Counter(
        token
        for tokens in document_tokens.values()
        for token in set(tokens)
    )
    document_count = len(documents)
    normalized_query = tuple(query_tokens[:BM25_QUERY_TOKEN_CAP])
    ranked: list[RankedEvent] = []
    for event in documents:
        tokens = document_tokens[event.event_id]
        frequencies = Counter(tokens)
        score = 0.0
        for term in normalized_query:
            frequency = frequencies[term]
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(
                1 + (document_count - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * len(tokens) / average_length
            )
            score += (
                inverse_document_frequency
                * frequency
                * (BM25_K1 + 1)
                / denominator
            )
        if not math.isfinite(score):
            raise ReplayIntegrityError("BM25 produced a non-finite score")
        ranked.append(RankedEvent(event=event, score=score))
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.event.event_sequence,
            item.event.event_id.encode("utf-8"),
        )
    )
    return tuple(ranked)


def _pack_retrieved_events(
    ranked: Sequence[RankedEvent], encoding: Encoding, excluded_ids: set[str]
) -> tuple[tuple[Event, ...], int]:
    accepted: list[Event] = []
    used = 0
    for ranked_event in ranked:
        if ranked_event.event.event_id in excluded_ids:
            continue
        if len(accepted) == BM25_TOP_K:
            break
        size = event_token_count(encoding, ranked_event.event)
        if size <= E_RETRIEVED_TOKEN_BUDGET - used:
            accepted.append(ranked_event.event)
            used += size
    return tuple(accepted), used


def build_bm25_context(
    step: EvaluationStep,
    encoding: Encoding,
    framing: PromptFraming,
    *,
    shared_events: Sequence[Event],
    isolation_challenge: IsolationChallenge,
) -> tuple[PackedContext, ScopeAudit, tuple[RankedEvent, ...]]:
    """Build E-BM25 with scope-first ranking and deterministic whole-event packing."""

    source_prefix = authoritative_prefix(step)
    recent = _select_recent_complete_suffix(
        source_prefix, encoding, E_RECENT_TOKEN_BUDGET
    )
    scoped_candidates = filter_event_scope(
        shared_events, step.tenant_id, step.conversation_id
    )
    source_by_id = {event.event_id: event for event in source_prefix}
    scoped_by_id = {event.event_id: event for event in scoped_candidates}
    if scoped_by_id != source_by_id:
        raise ReplayIntegrityError(
            "scoped retrieval candidates must equal the immutable authoritative prefix"
        )
    recent_ids = {event.event_id for event in recent.included}
    retrieval_candidates = tuple(
        event for event in scoped_candidates if event.event_id not in recent_ids
    )
    ranked = rank_bm25(
        retrieval_candidates,
        contextual_query_tokens(step),
        tenant_id=step.tenant_id,
        conversation_id=step.conversation_id,
    )
    retrieved, retrieved_tokens = _pack_retrieved_events(
        ranked, encoding, recent_ids
    )
    delivered = retrieved + recent.included
    audit = validate_isolation_challenge(
        shared_events,
        tenant_id=step.tenant_id,
        conversation_id=step.conversation_id,
        challenge=isolation_challenge,
        current_question=step.current_question,
        authoritative_events=source_prefix,
        delivered_events=delivered,
    )
    framing_text = framing.render(step.current_question)
    overhead = _validate_framing(encoding, framing_text)
    history = "".join(canonical_event_text(event) for event in delivered)
    packed = PackedContext(
        arm_id="E-BM25",
        delivered_events=delivered,
        historical_tokens=recent.used_tokens + retrieved_tokens,
        overhead_tokens=overhead,
        prompt_text=history + framing_text,
        recent_event_ids=tuple(event.event_id for event in recent.included),
        retrieved_event_ids=tuple(event.event_id for event in retrieved),
    )
    if packed.historical_tokens > B_HISTORY_TOKEN_BUDGET:
        raise ReplayIntegrityError("E-BM25 exceeds its historical token budget")
    if packed.total_input_tokens > 4_608:
        raise ReplayIntegrityError("E-BM25 exceeds its maximum input budget")
    return packed, audit, ranked


def build_evaluation_step_audit(
    step: EvaluationStep,
    encoding: Encoding,
    *,
    scope_audit: ScopeAudit,
    delivered_sources_by_arm: dict[str, Sequence[Event]],
) -> EvaluationStepAudit:
    """Derive pressure, gold-location, delivery, and isolation evidence from replay."""

    source_prefix = authoritative_prefix(step)
    b_selection = _select_recent_complete_suffix(
        source_prefix, encoding, B_HISTORY_TOKEN_BUDGET
    )
    included_event_ids = tuple(event.event_id for event in b_selection.included)
    excluded_event_ids = tuple(event.event_id for event in b_selection.excluded)
    included_message_ids = tuple(
        message.message_id
        for event in b_selection.included
        for message in event.messages
    )
    excluded_message_ids = tuple(
        message.message_id
        for event in b_selection.excluded
        for message in event.messages
    )
    source_by_id = {event.event_id: event for event in source_prefix}
    delivered_rows: list[tuple[str, tuple[str, ...]]] = []
    for arm_id, arm_events in sorted(delivered_sources_by_arm.items()):
        arm_event_ids: list[str] = []
        for event in arm_events:
            if (
                not event.confirmed
                or (event.tenant_id, event.conversation_id)
                != (step.tenant_id, step.conversation_id)
                or source_by_id.get(event.event_id) != event
            ):
                raise IsolationViolation(
                    "delivered source is cross-scope or outside the authoritative prefix"
                )
            arm_event_ids.append(event.event_id)
        delivered_rows.append((arm_id, tuple(arm_event_ids)))
    delivered = tuple(delivered_rows)
    canary_ids = {
        scope_audit.wrong_tenant_canary_event_id,
        scope_audit.wrong_conversation_canary_event_id,
    }
    delivered_ids = {
        event_id for _, arm_event_ids in delivered for event_id in arm_event_ids
    }
    gold_events = set(step.gold_event_ids)
    gold_messages = set(step.gold_message_ids)
    all_gold_outside = bool(gold_events or gold_messages) and (
        gold_events <= set(excluded_event_ids)
        and gold_messages <= set(excluded_message_ids)
        and gold_events.isdisjoint(included_event_ids)
        and gold_messages.isdisjoint(included_message_ids)
    )
    return EvaluationStepAudit(
        step_id=step.step_id,
        step_type=step.step_type,
        tenant_id=step.tenant_id,
        conversation_id=step.conversation_id,
        language=step.language,
        authoritative_prefix_tokens=sum(
            event_token_count(encoding, event) for event in source_prefix
        ),
        b_useful_history_capacity_tokens=B_HISTORY_TOKEN_BUDGET,
        b_included_event_ids=included_event_ids,
        b_excluded_event_ids=excluded_event_ids,
        b_included_message_ids=included_message_ids,
        b_excluded_message_ids=excluded_message_ids,
        gold_event_ids=tuple(sorted(step.gold_event_ids)),
        gold_message_ids=tuple(sorted(step.gold_message_ids)),
        b_truncated=b_selection.truncated,
        all_required_gold_outside_b=all_gold_outside,
        current_fact_atoms=tuple(sorted(step.gold_atoms)),
        superseded_fact_atoms=tuple(sorted(step.superseded_atoms)),
        abstention_required=step.abstention_required,
        delivered_source_ids_by_arm=delivered,
        shared_prefilter_corpus_count=scope_audit.shared_prefilter_corpus_count,
        wrong_tenant_prefilter_count=scope_audit.wrong_tenant_prefilter_count,
        wrong_conversation_prefilter_count=(
            scope_audit.wrong_conversation_prefilter_count
        ),
        postfilter_candidate_count=scope_audit.postfilter_candidate_count,
        wrong_tenant_canary_event_id=scope_audit.wrong_tenant_canary_event_id,
        wrong_conversation_canary_event_id=(
            scope_audit.wrong_conversation_canary_event_id
        ),
        canaries_absent_postfilter=scope_audit.canaries_absent_postfilter,
        canaries_absent_delivered_sources=not bool(canary_ids & delivered_ids),
    )
