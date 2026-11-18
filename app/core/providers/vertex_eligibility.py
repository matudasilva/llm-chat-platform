"""Isolated matching against caller-trusted capability records.

These records do not establish issuer authenticity, account access or live health.
This component is not connected to runtime provider selection or serialization.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityRecord:
    model: str
    projects: object
    locations: object
    max_output: int
    transports: object
    certification_id: str


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _project(value: object) -> bool:
    return _text(value) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", value) is not None


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _collection(value: object, validator) -> frozenset[str] | None:
    # Strings and mappings are not capability collections; validate before hashing.
    if not isinstance(value, (list, tuple, set, frozenset)) or not value:
        return None
    if not all(validator(member) for member in value):
        return None
    return frozenset(value)


@dataclass(frozen=True, init=False)
class CandidateEligibility:
    """Immutable snapshot; any malformed or duplicate record invalidates it."""

    _records: tuple[CapabilityRecord, ...]
    _valid: bool

    def __init__(self, records: object):
        snapshots = []
        valid = isinstance(records, (list, tuple, set, frozenset)) and bool(records)
        seen = set()
        if valid:
            for record in records:
                if type(record) is not CapabilityRecord:
                    valid = False
                    break
                projects = _collection(record.projects, _project)
                locations = _collection(record.locations, _text)
                transports = _collection(record.transports, _text)
                if (not _text(record.model) or not _text(record.certification_id)
                        or not _positive(record.max_output) or projects is None
                        or locations is None or transports is None or record.model in seen):
                    valid = False
                    break
                seen.add(record.model)
                snapshots.append(CapabilityRecord(record.model, projects, locations,
                                                  record.max_output, transports, record.certification_id))
        object.__setattr__(self, "_records", tuple(snapshots) if valid else ())
        object.__setattr__(self, "_valid", valid)

    def eligible(self, *, project: object, location: object, model: object,
                 configured_output: object, requested_output: object, transport: object) -> bool:
        if (not self._valid or not _project(project) or not _text(location)
                or not _text(model) or not _text(transport)
                or not _positive(configured_output) or not _positive(requested_output)):
            return False
        return any(record.model == model and project in record.projects
                   and location in record.locations and transport in record.transports
                   and configured_output <= record.max_output and requested_output <= record.max_output
                   for record in self._records)
