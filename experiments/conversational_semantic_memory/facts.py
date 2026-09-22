"""Pure, forward-only fact updates; event identities never depend on wall time."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata
from typing import Literal, Mapping, Sequence

from .events import canonical_bytes, sha256_hex

FACT_ID_ENCODING = "orq39-fact-id-v1"
KINDS = frozenset({"stable_fact", "duplicate", "update", "contradiction_trap",
                   "distractor", "isolation_canary", "no_memory", "historical", "prohibited"})


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected non-empty text")
    value.encode("utf-8", errors="strict")
    return unicodedata.normalize("NFC", value)


def _integer(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("expected a non-negative integer")


def fact_id(tenant_id: str, conversation_id: str, slot_key: str,
            source_sequence: int, op_index_within_extraction: int) -> str:
    """Hash v1 canonical JSON: named NFC strings and JSON integers, no delimiters.

    NFC-equivalent identities intentionally coincide. NFKC compatibility forms
    remain distinct; normalization cannot move text across named field boundaries.
    """
    _integer(source_sequence)
    _integer(op_index_within_extraction)
    return sha256_hex(canonical_bytes({
        "encoding_version": FACT_ID_ENCODING,
        "tenant_id": _text(tenant_id), "conversation_id": _text(conversation_id),
        "slot_key": _text(slot_key), "source_sequence": source_sequence,
        "op_index_within_extraction": op_index_within_extraction,
    }))


def normalize_value(value: str) -> str:
    """Match the ORQ-29 dedup normalization without importing its experiment."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


@dataclass(frozen=True, slots=True)
class Operation:
    op: Literal["assert", "retract"]
    slot_key: str
    value: str | None
    kind: str
    source_message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.op not in {"assert", "retract"}:
            raise ValueError("unknown operation")
        if not isinstance(self.slot_key, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.slot_key):
            raise ValueError("slot_key must be snake_case")
        if self.kind not in KINDS:
            raise ValueError("unknown kind")
        if self.op == "assert":
            _text(self.value)
        elif self.value is not None:
            raise ValueError("retract requires null value")
        if not isinstance(self.source_message_ids, tuple) or not self.source_message_ids:
            raise ValueError("non-empty provenance tuple required")
        for source in self.source_message_ids:
            _text(source)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Operation:
        """Accept the extractor's exact object schema without repairing fields."""
        if set(payload) != {"op", "slot_key", "value", "kind", "source_message_ids"}:
            raise ValueError("unexpected operation fields")
        sources = payload["source_message_ids"]
        if not isinstance(sources, list):
            raise ValueError("source_message_ids must be a JSON array")
        return cls(payload["op"], payload["slot_key"], payload["value"],
                   payload["kind"], tuple(sources))


@dataclass(frozen=True, slots=True)
class Fact:
    fact_id: str
    tenant_id: str
    conversation_id: str
    slot_key: str
    value: str
    kind: str
    statement: str
    source_message_ids: tuple[str, ...]
    source_sequence: int
    status: Literal["active", "superseded", "retracted"]
    supersedes: str | None
    superseded_by: str | None
    extractor_version: str


@dataclass(frozen=True, slots=True)
class AuditOperation:
    reason: Literal["retract_without_active_fact", "prohibited"]
    operation: Operation
    source_sequence: int
    op_index_within_extraction: int


@dataclass(frozen=True, slots=True)
class FactStore:
    tenant_id: str
    conversation_id: str
    extractor_version: str
    facts: tuple[Fact, ...] = ()
    audit: tuple[AuditOperation, ...] = ()
    last_sequence: int = -1

    def __post_init__(self) -> None:
        for name in ("tenant_id", "conversation_id", "extractor_version"):
            object.__setattr__(self, name, _text(getattr(self, name)))


def apply(store: FactStore, operations: Sequence[Operation | Mapping[str, object]], *,
          source_sequence: int, statement: str) -> FactStore:
    """Apply one complete extraction atomically; reject backward or repeated turns.

    The caller supplies the source assertion text because the operation schema
    does not include a statement. Prohibited operations are retained only in audit.
    """
    _integer(source_sequence)
    if source_sequence <= store.last_sequence:
        raise ValueError("extractions must advance the message sequence")
    statement = _text(statement)
    facts, audit = list(store.facts), list(store.audit)
    for index, operation in enumerate(operations):
        if isinstance(operation, Mapping):
            operation = Operation.from_payload(operation)
        if not isinstance(operation, Operation):
            raise ValueError("expected validated Operation")
        if operation.kind == "prohibited":
            audit.append(AuditOperation("prohibited", operation, source_sequence, index))
            continue
        active = next((i for i, fact in enumerate(facts)
                       if fact.slot_key == operation.slot_key and fact.status == "active"), None)
        prior = facts[active] if active is not None else None
        if operation.op == "retract":
            if prior is None:
                audit.append(AuditOperation("retract_without_active_fact", operation, source_sequence, index))
            else:
                facts[active] = replace(prior, status="retracted", superseded_by=None)
            continue
        if prior is not None and normalize_value(prior.value) == normalize_value(operation.value):
            facts[active] = replace(prior, source_message_ids=tuple(dict.fromkeys(
                prior.source_message_ids + operation.source_message_ids)))
            continue
        identifier = fact_id(store.tenant_id, store.conversation_id, operation.slot_key,
                             source_sequence, index)
        if prior is not None:
            facts[active] = replace(prior, status="superseded", superseded_by=identifier)
        facts.append(Fact(identifier, store.tenant_id, store.conversation_id,
                          operation.slot_key, operation.value, operation.kind, statement,
                          operation.source_message_ids, source_sequence, "active",
                          prior.fact_id if prior else None, None, store.extractor_version))
    return replace(store, facts=tuple(facts), audit=tuple(audit), last_sequence=source_sequence)
