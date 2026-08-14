from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from .protocol import ALLOWED_SPLITS, ProtocolError, require_allowed_split, sha256_file


SCHEMA_VERSION = "orq29-conversation-dataset-v1"
SUPPORTED_ROLES = {"user", "assistant"}


class DatasetError(ValueError):
    """The synthetic ORQ-29 dataset violates its frozen schema."""


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    message_id: str
    sequence: int
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class GoldFact:
    fact_key: str
    value: str
    value_type: str
    source_role: str
    eligible: bool
    prohibited: bool
    status: str
    supersedes_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    event_id: str
    sequence: int
    event_type: str
    messages: tuple[TranscriptMessage, ...]
    gold_facts: tuple[GoldFact, ...]

    @property
    def text(self) -> str:
        return "\n".join(f"{message.role}: {message.content}" for message in self.messages)


@dataclass(frozen=True, slots=True)
class AnswerExpectation:
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationStep:
    step_id: str
    query_event_id: str
    gold_source_event_ids: tuple[str, ...]
    gold_source_message_ids: tuple[str, ...]
    superseded_source_event_ids: tuple[str, ...]
    fact_key: str
    expected_value: str
    effective_sequence: int
    semantic_required: bool
    fallback_required: bool
    fallback_rationale: str
    b_answerable: bool
    slices: tuple[str, ...]
    expected: AnswerExpectation


@dataclass(frozen=True, slots=True)
class ConversationFixture:
    schema_version: str
    split: str
    tenant_id: str
    conversation_id: str
    language: str
    synthetic: bool
    events: tuple[ConversationEvent, ...]
    evaluations: tuple[EvaluationStep, ...]

    def event_by_id(self, event_id: str) -> ConversationEvent:
        for event in self.events:
            if event.event_id == event_id:
                return event
        raise DatasetError(f"unknown event_id {event_id!r}")

    def prefix_before(self, event_id: str) -> tuple[ConversationEvent, ...]:
        query = self.event_by_id(event_id)
        return tuple(event for event in self.events if event.sequence < query.sequence)

    def query_and_reference(self, evaluation: EvaluationStep) -> tuple[TranscriptMessage, TranscriptMessage]:
        event = self.event_by_id(evaluation.query_event_id)
        if len(event.messages) != 2:
            raise DatasetError("evaluation event must contain a user/assistant exchange")
        return event.messages[0], event.messages[1]


def load_dataset(path: Path, *, expected_split: str) -> tuple[ConversationFixture, ...]:
    require_allowed_split(expected_split)
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DatasetError(f"dataset unavailable: {path}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise DatasetError("dataset rows must be objects")
        rows.append(row)
    fixtures = tuple(_parse_fixture(row) for row in rows)
    validate_dataset(fixtures, expected_split=expected_split)
    return fixtures


def verify_dataset_manifest(path: Path, *, development_manifest_sha256: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError("dataset manifest is unavailable or invalid") from exc
    if payload.get("schema_version") != "orq29-dataset-manifest-v1":
        raise DatasetError("dataset manifest schema is invalid")
    if payload.get("development_manifest_sha256") != development_manifest_sha256:
        raise DatasetError("dataset manifest is not bound to the approved development manifest")
    heldout = payload.get("heldout")
    if heldout != {"bundle": None, "hash": None, "path": None, "seed": None, "status": "not_generated_not_accessible"}:
        raise DatasetError("dataset manifest exposes or materializes held-out state")
    for split in sorted(ALLOWED_SPLITS):
        item = payload.get(split)
        if not isinstance(item, dict):
            raise DatasetError(f"dataset manifest is missing {split}")
        dataset_path = path.parent / str(item.get("path"))
        if sha256_file(dataset_path) != item.get("sha256"):
            raise DatasetError(f"{split} dataset hash mismatch")
        fixtures = load_dataset(dataset_path, expected_split=split)
        if len(fixtures) != item.get("conversations"):
            raise DatasetError(f"{split} conversation count mismatch")
        if sum(len(fixture.evaluations) for fixture in fixtures) != item.get("evaluation_steps"):
            raise DatasetError(f"{split} evaluation count mismatch")
    return payload


def validate_dataset(fixtures: Sequence[ConversationFixture], *, expected_split: str) -> None:
    if not fixtures:
        raise DatasetError("dataset must contain conversations")
    require_allowed_split(expected_split)
    tenants: set[str] = set()
    languages: set[str] = set()
    conversation_ids: set[str] = set()
    event_ids: set[str] = set()
    message_ids: set[str] = set()
    step_ids: set[str] = set()
    for fixture in fixtures:
        if fixture.schema_version != SCHEMA_VERSION:
            raise DatasetError("unsupported dataset schema")
        if fixture.split != expected_split:
            raise DatasetError("fixture split differs from requested split")
        if not fixture.synthetic:
            raise DatasetError("only synthetic fixtures are permitted")
        _require_uuid(fixture.tenant_id, "tenant_id")
        _require_uuid(fixture.conversation_id, "conversation_id")
        if fixture.conversation_id in conversation_ids:
            raise DatasetError("conversation IDs must be globally unique")
        conversation_ids.add(fixture.conversation_id)
        tenants.add(fixture.tenant_id)
        languages.add(fixture.language)
        _validate_fixture(fixture, event_ids, message_ids, step_ids)
    if len(tenants) != 4:
        raise DatasetError("each materialized split must contain four synthetic tenants")
    if languages != {"en", "es"}:
        raise DatasetError("each materialized split must contain English and Spanish")


def _parse_fixture(value: MappingLike) -> ConversationFixture:
    required = {"schema_version", "split", "tenant_id", "conversation_id", "language", "synthetic", "events", "evaluations"}
    if set(value) != required:
        raise DatasetError(f"fixture fields differ: {sorted(set(value) ^ required)}")
    events_raw = value["events"]
    evaluations_raw = value["evaluations"]
    if not isinstance(events_raw, list) or not isinstance(evaluations_raw, list):
        raise DatasetError("events and evaluations must be arrays")
    return ConversationFixture(
        schema_version=_string(value["schema_version"], "schema_version"),
        split=_string(value["split"], "split"),
        tenant_id=_string(value["tenant_id"], "tenant_id"),
        conversation_id=_string(value["conversation_id"], "conversation_id"),
        language=_string(value["language"], "language"),
        synthetic=_boolean(value["synthetic"], "synthetic"),
        events=tuple(_parse_event(item) for item in events_raw),
        evaluations=tuple(_parse_evaluation(item) for item in evaluations_raw),
    )


MappingLike = dict[str, Any]


def _parse_event(value: Any) -> ConversationEvent:
    required = {"event_id", "sequence", "event_type", "messages", "gold_facts"}
    if not isinstance(value, dict) or set(value) != required:
        raise DatasetError("event fields are invalid")
    messages = value["messages"]
    facts = value["gold_facts"]
    if not isinstance(messages, list) or not isinstance(facts, list):
        raise DatasetError("event messages and gold facts must be arrays")
    return ConversationEvent(
        event_id=_string(value["event_id"], "event_id"),
        sequence=_integer(value["sequence"], "event.sequence"),
        event_type=_string(value["event_type"], "event_type"),
        messages=tuple(_parse_message(item) for item in messages),
        gold_facts=tuple(_parse_gold_fact(item) for item in facts),
    )


def _parse_gold_fact(value: Any) -> GoldFact:
    required = {
        "fact_key", "value", "value_type", "source_role", "eligible",
        "prohibited", "status", "supersedes_event_ids",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise DatasetError("gold fact fields are invalid")
    return GoldFact(
        fact_key=_string(value["fact_key"], "fact_key"),
        value=_string(value["value"], "fact.value"),
        value_type=_string(value["value_type"], "value_type"),
        source_role=_string(value["source_role"], "source_role"),
        eligible=_boolean(value["eligible"], "eligible"),
        prohibited=_boolean(value["prohibited"], "prohibited"),
        status=_string(value["status"], "fact.status"),
        supersedes_event_ids=_strings(
            value["supersedes_event_ids"], "supersedes_event_ids", allow_empty=True
        ),
    )


def _parse_message(value: Any) -> TranscriptMessage:
    required = {"message_id", "sequence", "role", "content"}
    if not isinstance(value, dict) or set(value) != required:
        raise DatasetError("message fields are invalid")
    return TranscriptMessage(
        message_id=_string(value["message_id"], "message_id"),
        sequence=_integer(value["sequence"], "message.sequence"),
        role=_string(value["role"], "role"),
        content=_string(value["content"], "content").replace("\r\n", "\n").replace("\r", "\n"),
    )


def _parse_evaluation(value: Any) -> EvaluationStep:
    required = {
        "step_id", "query_event_id", "gold_source_event_ids", "gold_source_message_ids",
        "superseded_source_event_ids", "fact_key", "expected_value", "effective_sequence",
        "semantic_required", "fallback_required", "fallback_rationale", "b_answerable",
        "slices", "expected",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise DatasetError("evaluation fields are invalid")
    expected = value["expected"]
    if not isinstance(expected, dict) or set(expected) != {"required_terms", "forbidden_terms"}:
        raise DatasetError("answer expectation fields are invalid")
    return EvaluationStep(
        step_id=_string(value["step_id"], "step_id"),
        query_event_id=_string(value["query_event_id"], "query_event_id"),
        gold_source_event_ids=_strings(value["gold_source_event_ids"], "gold_source_event_ids"),
        gold_source_message_ids=_strings(value["gold_source_message_ids"], "gold_source_message_ids"),
        superseded_source_event_ids=_strings(value["superseded_source_event_ids"], "superseded_source_event_ids", allow_empty=True),
        fact_key=_string(value["fact_key"], "fact_key"),
        expected_value=_string(value["expected_value"], "expected_value"),
        effective_sequence=_integer(value["effective_sequence"], "effective_sequence"),
        semantic_required=_boolean(value["semantic_required"], "semantic_required"),
        fallback_required=_boolean(value["fallback_required"], "fallback_required"),
        fallback_rationale=_string(value["fallback_rationale"], "fallback_rationale"),
        b_answerable=_boolean(value["b_answerable"], "b_answerable"),
        slices=_strings(value["slices"], "slices"),
        expected=AnswerExpectation(
            required_terms=_strings(expected["required_terms"], "required_terms"),
            forbidden_terms=_strings(expected["forbidden_terms"], "forbidden_terms", allow_empty=True),
        ),
    )


def _validate_fixture(
    fixture: ConversationFixture,
    global_event_ids: set[str],
    global_message_ids: set[str],
    global_step_ids: set[str],
) -> None:
    if len(fixture.events) != 12:
        raise DatasetError("each conversation must contain twelve explicit exchange events")
    if [event.sequence for event in fixture.events] != list(range(1, 13)):
        raise DatasetError("event sequences must be contiguous")
    expected_message_sequence = 1
    local_events: set[str] = set()
    local_messages: set[str] = set()
    message_to_event: dict[str, str] = {}
    for event in fixture.events:
        _require_uuid(event.event_id, "event_id")
        if event.event_id in global_event_ids:
            raise DatasetError("event IDs must be globally unique")
        global_event_ids.add(event.event_id)
        local_events.add(event.event_id)
        if event.event_type != "exchange" or len(event.messages) != 2:
            raise DatasetError("Gate 1 fixtures use explicit two-message exchanges")
        if [message.role for message in event.messages] != ["user", "assistant"]:
            raise DatasetError("exchange roles must be user then assistant")
        for message in event.messages:
            _require_uuid(message.message_id, "message_id")
            if message.message_id in global_message_ids:
                raise DatasetError("message IDs must be globally unique")
            if message.sequence != expected_message_sequence:
                raise DatasetError("message sequences must be contiguous")
            if message.role not in SUPPORTED_ROLES or not message.content.strip():
                raise DatasetError("message role/content is invalid")
            expected_message_sequence += 1
            global_message_ids.add(message.message_id)
            local_messages.add(message.message_id)
            message_to_event[message.message_id] = event.event_id
        for fact in event.gold_facts:
            if fact.source_role not in SUPPORTED_ROLES:
                raise DatasetError("gold fact source role is invalid")
            if fact.prohibited and fact.eligible:
                raise DatasetError("prohibited facts cannot be eligible")
            if not set(fact.supersedes_event_ids).issubset(local_events):
                raise DatasetError("fact supersession must reference an earlier local event")
    if len(fixture.evaluations) != 4:
        raise DatasetError("each conversation must contain four evaluation steps")
    for evaluation in fixture.evaluations:
        if evaluation.step_id in global_step_ids:
            raise DatasetError("step IDs must be globally unique")
        global_step_ids.add(evaluation.step_id)
        query = fixture.event_by_id(evaluation.query_event_id)
        if any(fixture.event_by_id(source).sequence >= query.sequence for source in evaluation.gold_source_event_ids):
            raise DatasetError("gold events must precede the query")
        if not set(evaluation.gold_source_event_ids).issubset(local_events):
            raise DatasetError("gold event belongs to another conversation")
        if not set(evaluation.gold_source_message_ids).issubset(local_messages):
            raise DatasetError("gold message belongs to another conversation")
        if {message_to_event[item] for item in evaluation.gold_source_message_ids} != set(evaluation.gold_source_event_ids):
            raise DatasetError("gold message/event provenance is inconsistent")
        if evaluation.fallback_required and (
            not evaluation.b_answerable or evaluation.fallback_rationale == "not_required"
        ):
            raise DatasetError("fallback-required labels must be B-answerable and justified")
        if not evaluation.fallback_required and evaluation.fallback_rationale != "not_required":
            raise DatasetError("non-fallback labels must use not_required rationale")


def _strings(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DatasetError(f"{field} must be an array of non-empty strings")
    if not value and not allow_empty:
        raise DatasetError(f"{field} must not be empty")
    return tuple(value)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DatasetError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DatasetError(f"{field} must be an integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise DatasetError(f"{field} must be a boolean")
    return value


def _require_uuid(value: str, field: str) -> None:
    try:
        UUID(value)
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"{field} must be a UUID") from exc


def deny_heldout_path(path: Path) -> None:
    if "heldout" in {part.casefold().replace("-", "").replace("_", "") for part in path.parts}:
        raise ProtocolError("held-out paths are prohibited during development")
