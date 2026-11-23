"""Validated, server-owned manual model catalog values.

The allowlist is supplied by the operator; membership is not evidence of model
availability, lifecycle, access or price. Parsing has no provider side effects.
"""

from __future__ import annotations

import json
import math
import uuid
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel
import re
from dataclasses import dataclass
from typing import Literal

Provider = Literal["bedrock", "vertex"]
AllowedModel = tuple[Provider, str, str]

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_LOCATION = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
# Keep in sync with the Vertex adapter's explicit supported location set.
_VERTEX_LOCATIONS = frozenset({
    "global", "us", "eu", "us-central1", "us-east1", "us-east4", "us-east5",
    "us-south1", "us-west1", "us-west4", "northamerica-northeast1",
    "northamerica-northeast2", "southamerica-east1", "southamerica-west1",
    "europe-central2", "europe-north1", "europe-southwest1", "europe-west1",
    "europe-west2", "europe-west3", "europe-west4", "europe-west6",
    "europe-west8", "europe-west9", "europe-west12", "asia-east1",
    "asia-east2", "asia-northeast1", "asia-northeast3", "asia-south1",
    "asia-southeast1", "asia-southeast2", "australia-southeast1",
    "australia-southeast2", "me-central1", "me-central2", "me-west1",
    "africa-south1",
})
_BEDROCK_REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+\Z")
_MAX_OUTPUT_TOKENS = 65536
_FIELDS = frozenset({"id", "enabled", "display_name", "description", "provider", "model", "location", "max_output_tokens"})


def _safe_display(value: object, *, maximum: int, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= maximum
        and (allow_empty or bool(value))
        and value == value.strip()
        and all(character.isprintable() and character not in "<>" for character in value)
    )


@dataclass(frozen=True, slots=True)
class ManualModelEntry:
    id: str
    enabled: bool
    display_name: str
    description: str
    provider: Provider
    model: str
    location: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class ManualModelDisplay:
    id: str
    display_name: str
    description: str


@dataclass(frozen=True, slots=True)
class ManualModelCatalog:
    entries: tuple[ManualModelEntry, ...] = ()

    def resolve(self, model_id: str) -> ManualModelEntry | None:
        """Return only selectable entries; disabled and unknown IDs are equivalent."""
        return next((entry for entry in self.entries if entry.id == model_id and entry.enabled), None)

    def display(self) -> tuple[ManualModelDisplay, ...]:
        return tuple(
            ManualModelDisplay(entry.id, entry.display_name, entry.description)
            for entry in self.entries if entry.enabled
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("manual model catalog has duplicate fields")
        result[key] = value
    return result


def parse_manual_model_catalog(
    raw: str | None = None, *, allowed_models: frozenset[AllowedModel] = frozenset()
) -> ManualModelCatalog:
    """Parse a complete JSON array, rejecting the entire catalog on any error.

    ``allowed_models`` contains explicitly approved (provider, model, location)
    triples. The default catalog and allowlist are empty.
    """
    if raw is None:
        return ManualModelCatalog()
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as exc:
        raise ValueError("manual model catalog must be a JSON array") from exc
    if not isinstance(data, list):
        raise ValueError("manual model catalog must be a JSON array")
    entries: list[ManualModelEntry] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or item.keys() != _FIELDS:
            raise ValueError("manual model catalog entry has invalid fields")
        model_id, enabled = item["id"], item["enabled"]
        name, description = item["display_name"], item["description"]
        provider, model, location = item["provider"], item["model"], item["location"]
        cap = item["max_output_tokens"]
        if not isinstance(model_id, str) or not _ID.fullmatch(model_id) or model_id in seen:
            raise ValueError("manual model catalog has an invalid or duplicate ID")
        if type(enabled) is not bool or not _safe_display(name, maximum=100) or not _safe_display(description, maximum=500, allow_empty=True):
            raise ValueError("manual model catalog has invalid display metadata or enabled flag")
        if (provider not in ("bedrock", "vertex") or not isinstance(model, str)
                or not _MODEL.fullmatch(model) or not isinstance(location, str)
                or not _LOCATION.fullmatch(location) or (provider, model, location) not in allowed_models):
            raise ValueError("manual model catalog has an unapproved provider, model or location")
        if type(cap) is not int or not 1 <= cap <= _MAX_OUTPUT_TOKENS:
            raise ValueError("manual model catalog has an invalid output cap")
        seen.add(model_id)
        entries.append(ManualModelEntry(model_id, enabled, name, description, provider, model, location, cap))
    return ManualModelCatalog(tuple(entries))


@dataclass(frozen=True, slots=True, repr=False)
class FrozenSettings:
    """Attribute-access snapshot whose nested collections cannot be mutated."""

    _values: Mapping[str, Any]

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return FrozenSettings(MappingProxyType({key: _freeze(getattr(value, key)) for key in type(value).model_fields}))
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ChatGeneration:
    settings: FrozenSettings
    catalog: ManualModelCatalog
    generation_id: str


def _parse_allowlist(raw: str) -> frozenset[AllowedModel]:
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as exc:
        raise ValueError("manual model allowlist must be a JSON array") from exc
    if not isinstance(data, list):
        raise ValueError("manual model allowlist must be a JSON array")
    result = set()
    for item in data:
        if (not isinstance(item, list) or len(item) != 3
                or item[0] not in ("bedrock", "vertex")
                or not isinstance(item[1], str) or not _MODEL.fullmatch(item[1])
                or not isinstance(item[2], str) or not _LOCATION.fullmatch(item[2])):
            raise ValueError("manual model allowlist contains an invalid triple")
        triple = tuple(item)
        if triple in result:
            raise ValueError("manual model allowlist contains a duplicate triple")
        result.add(triple)
    return frozenset(result)


def build_chat_generation(configuration: Any) -> ChatGeneration:
    """Validate and capture one startup-only catalog/settings generation.

    Call once before serving requests. Runtime reload and live mutation are not
    supported; a fresh validated generation requires an application restart.
    """
    allowed = _parse_allowlist(configuration.manual_model_allowlist_json)
    catalog = parse_manual_model_catalog(configuration.manual_model_catalog_json, allowed_models=allowed)
    for entry in catalog.entries:
        if entry.provider == "vertex" and entry.location not in _VERTEX_LOCATIONS:
            raise ValueError("Vertex catalog entry has unsupported location")
        if entry.provider == "bedrock" and not _BEDROCK_REGION.fullmatch(entry.location):
            raise ValueError("Bedrock catalog entry has invalid region")
    if any(entry.enabled and entry.provider == "vertex" for entry in catalog.entries):
        if not configuration.manual_vertex_enabled:
            raise ValueError("enabled Vertex catalog entries require the manual Vertex gate")
        if (not isinstance(configuration.vertex_project_id, str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", configuration.vertex_project_id)
                or any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", entry.model)
                       for entry in catalog.entries if entry.enabled and entry.provider == "vertex")
                or not math.isfinite(configuration.provider_timeout_s)
                or configuration.provider_timeout_s <= 0
                or not 1 <= configuration.vertex_max_attempts <= 5
                or not 0 <= configuration.vertex_backoff_base_ms <= configuration.vertex_backoff_max_ms <= 60000):
            raise ValueError("enabled Vertex catalog entries require valid independent settings")
    values = {key: _freeze(getattr(configuration, key)) for key in type(configuration).model_fields}
    values.update(database_url=configuration.database_url, redis_url=configuration.redis_url)
    return ChatGeneration(FrozenSettings(MappingProxyType(values)), catalog, uuid.uuid4().hex)
