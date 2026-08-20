"""Strict deterministic response parsing and answer scoring for ORQ-30."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .model import NONCE_PATTERN
CANONICAL_ABSTENTION_BYTES = b'{"decision":"abstain","values":[]}'
_ALLOWED_KEYS = {"decision", "values"}


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScoreResult:
    correct: bool
    parsed: bool
    failure_class: str | None
    decision: str | None
    values: tuple[str, ...]
    retry_allowed: bool = False


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _incorrect(
    failure_class: str,
    *,
    parsed: bool = False,
    decision: str | None = None,
    values: tuple[str, ...] = (),
) -> ScoreResult:
    return ScoreResult(
        correct=False,
        parsed=parsed,
        failure_class=failure_class,
        decision=decision,
        values=values,
        retry_allowed=False,
    )


def _strict_utf8(content: str | bytes) -> tuple[str, bytes] | None:
    try:
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="strict"), content
        if isinstance(content, str):
            return content, content.encode("utf-8", errors="strict")
    except UnicodeError:
        return None
    return None


def score_response(content: str | bytes, gold_atoms: frozenset[str]) -> ScoreResult:
    """Score exactly one raw JSON object without normalization, coercion, or repair."""

    decoded = _strict_utf8(content)
    if decoded is None:
        return _incorrect("parse_failure")
    text, raw = decoded
    decoder = json.JSONDecoder(
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonstandard_constant,
    )
    try:
        payload, end = decoder.raw_decode(text)
    except (json.JSONDecodeError, _DuplicateKey, ValueError):
        return _incorrect("parse_failure")
    if end != len(text):
        return _incorrect("parse_failure")
    if not isinstance(payload, dict):
        return _incorrect("format_failure", parsed=True)
    if set(payload) != _ALLOWED_KEYS:
        return _incorrect("format_failure", parsed=True)

    decision = payload["decision"]
    values_value = payload["values"]
    if not isinstance(decision, str) or decision not in {"answer", "abstain"}:
        return _incorrect("format_failure", parsed=True)
    if not isinstance(values_value, list) or any(
        not isinstance(value, str) for value in values_value
    ):
        return _incorrect("format_failure", parsed=True, decision=decision)
    values = tuple(values_value)
    if any(NONCE_PATTERN.fullmatch(value) is None for value in values):
        return _incorrect(
            "format_failure", parsed=True, decision=decision, values=values
        )
    if len(values) != len(set(values)):
        return _incorrect(
            "duplicate_value", parsed=True, decision=decision, values=values
        )

    if not gold_atoms:
        if raw == CANONICAL_ABSTENTION_BYTES:
            return ScoreResult(True, True, None, "abstain", (), False)
        return _incorrect(
            "incorrect_answer", parsed=True, decision=decision, values=values
        )
    if any(NONCE_PATTERN.fullmatch(atom) is None for atom in gold_atoms):
        raise ValueError("gold atom violates the frozen nonce contract")
    if decision != "answer" or not values:
        return _incorrect(
            "incorrect_answer", parsed=True, decision=decision, values=values
        )
    if set(values) != set(gold_atoms):
        return _incorrect(
            "incorrect_answer", parsed=True, decision=decision, values=values
        )
    return ScoreResult(True, True, None, decision, values, False)
