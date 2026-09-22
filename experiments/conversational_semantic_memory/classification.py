"""Strict answer classification with explicit, overlap-safe value identities."""

from __future__ import annotations

from dataclasses import dataclass
import json
import unicodedata


def normalize_alias(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True, slots=True)
class ValueEntry:
    value_id: str
    aliases: frozenset[str]
    roles: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", frozenset(self.aliases))
        object.__setattr__(self, "roles", frozenset(self.roles))
        if not isinstance(self.value_id, str) or not self.value_id or not self.aliases:
            raise ValueError("value identity and aliases are required")
        if not self.roles or not self.roles <= {"gold", "stale", "canary", "other"}:
            raise ValueError("invalid value roles")
        if any(not isinstance(alias, str) or not alias for alias in self.aliases):
            raise ValueError("aliases must be non-empty strings")


@dataclass(frozen=True, slots=True)
class ValueUniverse:
    entries: tuple[ValueEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        identities, aliases = set(), set()
        for entry in self.entries:
            normalized = {normalize_alias(alias) for alias in entry.aliases}
            if entry.value_id in identities or aliases & normalized:
                raise ValueError("duplicate value identity or ambiguous normalized alias")
            identities.add(entry.value_id)
            aliases.update(normalized)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonstandard JSON constant")


def parse_response(content: str | bytes) -> tuple[str, tuple[str, ...]] | None:
    """Reject repair, duplicate keys/values, invalid UTF-8, and extra fields.

    JSON whitespace is allowed. Unlike ORQ-30, values are authored aliases,
    not nonce tokens; abstention requires an empty values array.
    """
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if not isinstance(content, str):
            return None
        content.encode("utf-8")
        raw = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(raw, dict) or set(raw) != {"decision", "values"}:
            return None
        decision, values = raw["decision"], raw["values"]
        if not isinstance(decision, str) or decision not in {"answer", "abstain"}:
            return None
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return None
        for value in values:
            value.encode("utf-8")
        if len(set(values)) != len(values) or (decision == "abstain" and values):
            return None
        return decision, tuple(values)
    except (ValueError, UnicodeError, RecursionError):
        return None


def classify(content: str | bytes, universe: ValueUniverse) -> str:
    """First matching rule wins, including for mixed stale/canary answers."""
    parsed = parse_response(content)
    if parsed is None:
        return "non_conforming"
    decision, values = parsed
    aliases = {normalize_alias(alias): entry for entry in universe.entries for alias in entry.aliases}
    matched = [aliases.get(normalize_alias(value)) for value in values]
    if any(entry is not None and "canary" in entry.roles for entry in matched):
        return "contaminated_answer"
    if any(entry is not None and "stale" in entry.roles for entry in matched):
        return "stale_answer"
    gold = {entry.value_id for entry in universe.entries if "gold" in entry.roles}
    if not gold and decision == "abstain":
        return "correct"
    if decision == "answer" and gold and all(entry is not None for entry in matched):
        if {entry.value_id for entry in matched} == gold:
            return "correct"
    if decision == "abstain":
        return "abstain"
    return "incorrect"
