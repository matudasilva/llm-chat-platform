"""Validated schemas for ORQ-30 conversational events and evaluation steps."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


STEP_TYPES = {
    "primary_out_of_window_one",
    "primary_out_of_window_two",
    "recent_evidence_control",
    "no_evidence_distractor_isolation_control",
}
NONCE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$", flags=re.ASCII)


def _require_nonempty_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Message:
    """One source message in an immutable confirmed event."""

    message_id: str
    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        _require_nonempty_text(self.message_id, "message_id")
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("role must be system, user, or assistant")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")

    def canonical_payload(self) -> dict[str, str]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
        }


@dataclass(frozen=True, slots=True)
class Event:
    """A scoped confirmed exchange or explicit conversational event.

    Scope and confirmation are control-plane metadata. The canonical prompt
    rendering contains only the event fields frozen by the ORQ-30 contract.
    """

    tenant_id: str
    conversation_id: str
    event_id: str
    event_sequence: int
    messages: tuple[Message, ...]
    confirmed: bool = True

    def __post_init__(self) -> None:
        _require_nonempty_text(self.tenant_id, "tenant_id")
        _require_nonempty_text(self.conversation_id, "conversation_id")
        _require_nonempty_text(self.event_id, "event_id")
        if isinstance(self.event_sequence, bool) or not isinstance(
            self.event_sequence, int
        ):
            raise ValueError("event_sequence must be an integer")
        if self.event_sequence < 0:
            raise ValueError("event_sequence must be zero or greater")
        if not self.messages:
            raise ValueError("messages must contain at least one message")
        message_ids = [message.message_id for message in self.messages]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("message_id values must be unique within an event")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_sequence": self.event_sequence,
            "messages": [message.canonical_payload() for message in self.messages],
        }

    def document_text(self) -> str:
        return "\n".join(message.content for message in self.messages)


@dataclass(frozen=True, slots=True)
class EvaluationStep:
    """An immutable teacher-forced evaluation prefix and current question."""

    step_id: str
    step_type: Literal[
        "primary_out_of_window_one",
        "primary_out_of_window_two",
        "recent_evidence_control",
        "no_evidence_distractor_isolation_control",
    ]
    tenant_id: str
    conversation_id: str
    language: Literal["en", "es"]
    current_question: str
    authoritative_events: tuple[Event, ...]
    gold_event_ids: frozenset[str] = frozenset()
    gold_message_ids: frozenset[str] = frozenset()
    gold_atoms: frozenset[str] = frozenset()
    superseded_atoms: frozenset[str] = frozenset()
    abstention_required: bool = False

    def __post_init__(self) -> None:
        _require_nonempty_text(self.step_id, "step_id")
        _require_nonempty_text(self.tenant_id, "tenant_id")
        _require_nonempty_text(self.conversation_id, "conversation_id")
        _require_nonempty_text(self.current_question, "current_question")
        if self.step_type not in STEP_TYPES:
            raise ValueError("step_type is outside the frozen four-step design")
        if self.language not in {"en", "es"}:
            raise ValueError("language must be en or es")
        if not self.authoritative_events:
            raise ValueError("authoritative_events must not be empty")
        event_ids = [event.event_id for event in self.authoritative_events]
        sequences = [event.event_sequence for event in self.authoritative_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event_id values must be unique within a prefix")
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("authoritative events must have unique ascending sequences")
        for event in self.authoritative_events:
            if not event.confirmed:
                raise ValueError("authoritative prefixes may contain only confirmed events")
            if (event.tenant_id, event.conversation_id) != (
                self.tenant_id,
                self.conversation_id,
            ):
                raise ValueError("authoritative prefix event is outside the step scope")
        if self.abstention_required != (not self.gold_atoms):
            raise ValueError("abstention_required must agree with gold_atoms emptiness")
        if any(
            NONCE_PATTERN.fullmatch(atom) is None
            for atom in self.gold_atoms | self.superseded_atoms
        ):
            raise ValueError("gold and superseded atoms must satisfy the nonce contract")
        if self.step_type == "no_evidence_distractor_isolation_control":
            if self.gold_event_ids or self.gold_message_ids or self.gold_atoms:
                raise ValueError("no-evidence steps cannot declare gold sources or atoms")
        elif (
            not self.gold_atoms
            or (not self.gold_event_ids and not self.gold_message_ids)
            or self.abstention_required
        ):
            raise ValueError("evidence-bearing steps require sources, atoms, and no abstention")

    @property
    def is_primary(self) -> bool:
        return self.step_type.startswith("primary_out_of_window_")


@dataclass(frozen=True, slots=True)
class EvaluationStepAudit:
    """Computed, data-independent schema for proving per-step context pressure."""

    step_id: str
    step_type: str
    tenant_id: str
    conversation_id: str
    language: str
    authoritative_prefix_tokens: int
    b_useful_history_capacity_tokens: int
    b_included_event_ids: tuple[str, ...]
    b_excluded_event_ids: tuple[str, ...]
    b_included_message_ids: tuple[str, ...]
    b_excluded_message_ids: tuple[str, ...]
    gold_event_ids: tuple[str, ...]
    gold_message_ids: tuple[str, ...]
    b_truncated: bool
    all_required_gold_outside_b: bool
    current_fact_atoms: tuple[str, ...]
    superseded_fact_atoms: tuple[str, ...]
    abstention_required: bool
    delivered_source_ids_by_arm: tuple[tuple[str, tuple[str, ...]], ...]
    shared_prefilter_corpus_count: int
    wrong_tenant_prefilter_count: int
    wrong_conversation_prefilter_count: int
    postfilter_candidate_count: int
    wrong_tenant_canary_event_id: str
    wrong_conversation_canary_event_id: str
    canaries_absent_postfilter: bool
    canaries_absent_delivered_sources: bool

    def __post_init__(self) -> None:
        count_fields = (
            self.authoritative_prefix_tokens,
            self.b_useful_history_capacity_tokens,
            self.shared_prefilter_corpus_count,
            self.wrong_tenant_prefilter_count,
            self.wrong_conversation_prefilter_count,
            self.postfilter_candidate_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in count_fields
        ):
            raise ValueError("audit token and corpus counts must be non-negative integers")
        if self.b_useful_history_capacity_tokens != 4_096:
            raise ValueError("B useful history capacity must remain exactly 4,096")
        if any(
            NONCE_PATTERN.fullmatch(atom) is None
            for atom in self.current_fact_atoms + self.superseded_fact_atoms
        ):
            raise ValueError("audit fact atoms must satisfy the nonce contract")
        if (
            self.shared_prefilter_corpus_count < 3
            or self.wrong_tenant_prefilter_count < 1
            or self.wrong_conversation_prefilter_count < 1
            or self.postfilter_candidate_count < 1
            or not self.wrong_tenant_canary_event_id
            or not self.wrong_conversation_canary_event_id
            or self.wrong_tenant_canary_event_id
            == self.wrong_conversation_canary_event_id
            or self.shared_prefilter_corpus_count
            < self.postfilter_candidate_count
            + self.wrong_tenant_prefilter_count
            + self.wrong_conversation_prefilter_count
        ):
            raise ValueError("isolation challenge evidence is missing or inconsistent")
        delivered_ids = {
            event_id
            for _, arm_event_ids in self.delivered_source_ids_by_arm
            for event_id in arm_event_ids
        }
        derived_canaries_absent_delivered = not bool(
            {
                self.wrong_tenant_canary_event_id,
                self.wrong_conversation_canary_event_id,
            }
            & delivered_ids
        )
        if (
            self.canaries_absent_delivered_sources
            != derived_canaries_absent_delivered
        ):
            raise ValueError("canary delivery absence must be derived from delivered IDs")
        included_events = set(self.b_included_event_ids)
        excluded_events = set(self.b_excluded_event_ids)
        included_messages = set(self.b_included_message_ids)
        excluded_messages = set(self.b_excluded_message_ids)
        if included_events & excluded_events or included_messages & excluded_messages:
            raise ValueError("B included and excluded sources must be disjoint")
        derived_truncated = bool(excluded_events or excluded_messages)
        if self.b_truncated != derived_truncated:
            raise ValueError("b_truncated must be derived from excluded B sources")
        gold_events = set(self.gold_event_ids)
        gold_messages = set(self.gold_message_ids)
        gold_present = bool(gold_events or gold_messages)
        gold_known = gold_events <= included_events | excluded_events and gold_messages <= (
            included_messages | excluded_messages
        )
        derived_gold_outside = (
            gold_present
            and gold_known
            and gold_events.isdisjoint(included_events)
            and gold_messages.isdisjoint(included_messages)
            and gold_events <= excluded_events
            and gold_messages <= excluded_messages
        )
        if self.all_required_gold_outside_b != derived_gold_outside:
            raise ValueError("gold-outside-B must be derived from recorded source locations")
        if self.step_type not in STEP_TYPES:
            raise ValueError("audit step_type is outside the frozen four-step design")
        if self.step_type in {
            "primary_out_of_window_one",
            "primary_out_of_window_two",
        }:
            if not 8_192 <= self.authoritative_prefix_tokens <= 16_384:
                raise ValueError("primary prefix must contain 8,192 to 16,384 tokens")
            if not self.b_truncated or not self.all_required_gold_outside_b:
                raise ValueError("primary steps require real B truncation and excluded gold")
            if not gold_present:
                raise ValueError("primary steps require at least one gold source")
            if not self.current_fact_atoms or self.abstention_required:
                raise ValueError("primary steps require current facts and no abstention")
        elif self.step_type == "recent_evidence_control":
            if not gold_present or not gold_known:
                raise ValueError("recent controls require known gold sources")
            if not gold_events <= included_events or not gold_messages <= included_messages:
                raise ValueError("recent-control gold must be inside B")
            if not self.current_fact_atoms or self.abstention_required:
                raise ValueError("recent controls require current facts and no abstention")
        elif self.step_type == "no_evidence_distractor_isolation_control":
            if gold_present or self.current_fact_atoms or not self.abstention_required:
                raise ValueError("no-evidence controls require empty gold and abstention")
        if self.abstention_required != (not self.current_fact_atoms):
            raise ValueError("audit abstention label must agree with current facts")
        if not self.canaries_absent_postfilter or not self.canaries_absent_delivered_sources:
            raise ValueError("isolation canaries must be absent after filtering and delivery")
