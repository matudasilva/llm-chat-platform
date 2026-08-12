from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import UUID


SUPPORTED_ROLES = {"user", "assistant"}
SUPPORTED_SPLITS = {"development", "heldout"}


class DatasetError(ValueError):
    """The frozen conversational dataset violates its declared contract."""


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    message_id: str
    sequence: int
    role: str
    content: str
    fact_key: str | None = None
    effective_sequence: int | None = None
    supersedes_source_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerExpectation:
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationStep:
    step_id: str
    query_message_id: str
    reference_answer_message_id: str
    gold_source_message_ids: tuple[str, ...]
    superseded_source_message_ids: tuple[str, ...]
    fact_key: str
    effective_sequence: int
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
    messages: tuple[TranscriptMessage, ...]
    evaluations: tuple[EvaluationStep, ...]

    def message_by_id(self, message_id: str) -> TranscriptMessage:
        for message in self.messages:
            if message.message_id == message_id:
                return message
        raise DatasetError(f"unknown message_id {message_id!r}")

    def prefix_before(self, message_id: str) -> tuple[TranscriptMessage, ...]:
        query = self.message_by_id(message_id)
        return tuple(message for message in self.messages if message.sequence < query.sequence)

    def messages_through(self, message_id: str) -> tuple[TranscriptMessage, ...]:
        boundary = self.message_by_id(message_id)
        return tuple(message for message in self.messages if message.sequence <= boundary.sequence)


def normalize_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path, *, expected_split: str | None = None) -> list[ConversationFixture]:
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
            raise DatasetError(f"dataset row {line_number} must be an object")
        rows.append(row)
    fixtures = [_parse_fixture(row) for row in rows]
    validate_dataset(fixtures, expected_split=expected_split)
    return fixtures


def validate_dataset(
    fixtures: Sequence[ConversationFixture],
    *,
    expected_split: str | None = None,
) -> None:
    if not fixtures:
        raise DatasetError("dataset must contain at least one conversation")
    conversation_owners: dict[str, str] = {}
    all_message_ids: set[str] = set()
    step_ids: set[str] = set()
    tenants: set[str] = set()
    languages: set[str] = set()
    for fixture in fixtures:
        if fixture.schema_version != "conversation-memory-dataset-v1":
            raise DatasetError("unsupported dataset schema_version")
        if fixture.split not in SUPPORTED_SPLITS:
            raise DatasetError(f"unsupported split {fixture.split!r}")
        if expected_split is not None and fixture.split != expected_split:
            raise DatasetError(
                f"expected split {expected_split!r}, found {fixture.split!r}"
            )
        if not fixture.synthetic:
            raise DatasetError("Gate 1 accepts synthetic fixtures only")
        _require_uuid(fixture.tenant_id, "tenant_id")
        _require_uuid(fixture.conversation_id, "conversation_id")
        previous_owner = conversation_owners.setdefault(
            fixture.conversation_id, fixture.tenant_id
        )
        if previous_owner != fixture.tenant_id:
            raise DatasetError("conversation_id reused across tenants")
        tenants.add(fixture.tenant_id)
        languages.add(fixture.language)
        _validate_conversation(fixture, all_message_ids, step_ids)
    if len(tenants) < 2:
        raise DatasetError("dataset must include at least two synthetic tenants")
    if not {"en", "es"}.issubset(languages):
        raise DatasetError("dataset must include English and Spanish fixtures")


def iter_exchange_pairs(
    fixture: ConversationFixture,
) -> Iterable[tuple[TranscriptMessage, TranscriptMessage]]:
    for index in range(0, len(fixture.messages), 2):
        yield fixture.messages[index], fixture.messages[index + 1]


def _parse_fixture(row: dict[str, Any]) -> ConversationFixture:
    required = {
        "schema_version",
        "split",
        "tenant_id",
        "conversation_id",
        "language",
        "synthetic",
        "messages",
        "evaluations",
    }
    if set(row) != required:
        raise DatasetError(f"fixture fields differ: {sorted(set(row) ^ required)}")
    messages_raw = row["messages"]
    evaluations_raw = row["evaluations"]
    if not isinstance(messages_raw, list) or not isinstance(evaluations_raw, list):
        raise DatasetError("messages and evaluations must be arrays")
    messages = tuple(_parse_message(value) for value in messages_raw)
    evaluations = tuple(_parse_evaluation(value) for value in evaluations_raw)
    return ConversationFixture(
        schema_version=_require_string(row["schema_version"], "schema_version"),
        split=_require_string(row["split"], "split"),
        tenant_id=_require_string(row["tenant_id"], "tenant_id"),
        conversation_id=_require_string(row["conversation_id"], "conversation_id"),
        language=_require_string(row["language"], "language"),
        synthetic=row["synthetic"] if isinstance(row["synthetic"], bool) else _bad("synthetic"),
        messages=messages,
        evaluations=evaluations,
    )


def _parse_message(value: Any) -> TranscriptMessage:
    if not isinstance(value, dict):
        raise DatasetError("message must be an object")
    allowed = {
        "message_id",
        "sequence",
        "role",
        "content",
        "fact_key",
        "effective_sequence",
        "supersedes_source_message_ids",
    }
    if not set(value).issubset(allowed) or not {
        "message_id",
        "sequence",
        "role",
        "content",
    }.issubset(value):
        raise DatasetError("message fields are invalid")
    supersedes = value.get("supersedes_source_message_ids", [])
    if not isinstance(supersedes, list) or not all(isinstance(item, str) for item in supersedes):
        raise DatasetError("supersedes_source_message_ids must be an array of strings")
    sequence = value["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise DatasetError("message sequence must be an integer")
    effective = value.get("effective_sequence")
    if effective is not None and (not isinstance(effective, int) or isinstance(effective, bool)):
        raise DatasetError("effective_sequence must be an integer or null")
    fact_key = value.get("fact_key")
    if fact_key is not None and not isinstance(fact_key, str):
        raise DatasetError("fact_key must be a string or null")
    return TranscriptMessage(
        message_id=_require_string(value["message_id"], "message_id"),
        sequence=sequence,
        role=_require_string(value["role"], "role"),
        content=normalize_line_endings(_require_string(value["content"], "content")),
        fact_key=fact_key,
        effective_sequence=effective,
        supersedes_source_message_ids=tuple(supersedes),
    )


def _parse_evaluation(value: Any) -> EvaluationStep:
    required = {
        "step_id",
        "query_message_id",
        "reference_answer_message_id",
        "gold_source_message_ids",
        "superseded_source_message_ids",
        "fact_key",
        "effective_sequence",
        "slices",
        "expected",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise DatasetError("evaluation fields are invalid")
    expected = value["expected"]
    if not isinstance(expected, dict) or set(expected) != {"required_terms", "forbidden_terms"}:
        raise DatasetError("evaluation expected fields are invalid")
    list_fields = (
        "gold_source_message_ids",
        "superseded_source_message_ids",
        "slices",
    )
    for field in list_fields:
        if not isinstance(value[field], list) or not all(
            isinstance(item, str) and item for item in value[field]
        ):
            raise DatasetError(f"{field} must be a non-empty-string array")
    for field in ("required_terms", "forbidden_terms"):
        if not isinstance(expected[field], list) or not all(
            isinstance(item, str) and item for item in expected[field]
        ):
            raise DatasetError(f"expected.{field} must be a string array")
    effective = value["effective_sequence"]
    if not isinstance(effective, int) or isinstance(effective, bool):
        raise DatasetError("evaluation effective_sequence must be an integer")
    return EvaluationStep(
        step_id=_require_string(value["step_id"], "step_id"),
        query_message_id=_require_string(value["query_message_id"], "query_message_id"),
        reference_answer_message_id=_require_string(
            value["reference_answer_message_id"], "reference_answer_message_id"
        ),
        gold_source_message_ids=tuple(value["gold_source_message_ids"]),
        superseded_source_message_ids=tuple(value["superseded_source_message_ids"]),
        fact_key=_require_string(value["fact_key"], "fact_key"),
        effective_sequence=effective,
        slices=tuple(value["slices"]),
        expected=AnswerExpectation(
            required_terms=tuple(expected["required_terms"]),
            forbidden_terms=tuple(expected["forbidden_terms"]),
        ),
    )


def _validate_conversation(
    fixture: ConversationFixture,
    all_message_ids: set[str],
    step_ids: set[str],
) -> None:
    if not fixture.messages or len(fixture.messages) % 2:
        raise DatasetError("conversation must contain complete user/assistant exchanges")
    sequences = [message.sequence for message in fixture.messages]
    if sequences != list(range(1, len(fixture.messages) + 1)):
        raise DatasetError("message sequences must be contiguous and strictly increasing")
    local_ids: set[str] = set()
    for index, message in enumerate(fixture.messages):
        _require_uuid(message.message_id, "message_id")
        if message.message_id in local_ids or message.message_id in all_message_ids:
            raise DatasetError("message_id values must be globally unique")
        local_ids.add(message.message_id)
        all_message_ids.add(message.message_id)
        expected_role = "user" if index % 2 == 0 else "assistant"
        if message.role != expected_role or message.role not in SUPPORTED_ROLES:
            raise DatasetError("transcript must alternate user and assistant roles")
        if not message.content.strip():
            raise DatasetError("message content must not be blank")
        if message.effective_sequence is not None and message.effective_sequence > message.sequence:
            raise DatasetError("effective_sequence cannot be after its source message")
        for superseded in message.supersedes_source_message_ids:
            if superseded not in local_ids:
                raise DatasetError("a message may supersede only an earlier local source")
    by_id = {message.message_id: message for message in fixture.messages}
    if not fixture.evaluations:
        raise DatasetError("each conversation needs evaluation steps")
    for evaluation in fixture.evaluations:
        if evaluation.step_id in step_ids:
            raise DatasetError("step_id values must be globally unique")
        step_ids.add(evaluation.step_id)
        query = by_id.get(evaluation.query_message_id)
        answer = by_id.get(evaluation.reference_answer_message_id)
        if query is None or answer is None:
            raise DatasetError("evaluation references an unknown query/reference answer")
        if query.role != "user" or answer.role != "assistant":
            raise DatasetError("evaluation query/answer roles are invalid")
        if answer.sequence != query.sequence + 1:
            raise DatasetError("reference answer must immediately follow its query")
        if not evaluation.gold_source_message_ids:
            raise DatasetError("evaluation needs at least one gold source message")
        for source_id in (
            *evaluation.gold_source_message_ids,
            *evaluation.superseded_source_message_ids,
        ):
            source = by_id.get(source_id)
            if source is None or source.sequence >= query.sequence:
                raise DatasetError("evaluation source must be in the authoritative prefix")
        if evaluation.effective_sequence >= query.sequence:
            raise DatasetError("evaluation effective_sequence must precede the query")
        if not evaluation.expected.required_terms:
            raise DatasetError("evaluation requires at least one expected term")


def _require_uuid(value: str, field: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise DatasetError(f"{field} must be a UUID") from exc


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DatasetError(f"{field} must be a non-empty string")
    return value


def _bad(field: str) -> Any:
    raise DatasetError(f"{field} has an invalid type")
