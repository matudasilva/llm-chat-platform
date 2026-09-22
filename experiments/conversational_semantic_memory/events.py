"""Append-only, hash-chained event log (spec §Diseño 14, H4).

Ordering claims in this experiment -- a freeze before a dispatch, a check
before a stage -- are proved by position in this chain and by hash equality,
never by file timestamps, which are mutable. Every event carries the sha256 of
the previous event; the genesis predecessor is a fixed zero hash. `verify`
recomputes the whole chain, so an edited, reordered, or truncated-in-the-middle
log fails closed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

GENESIS_PREVIOUS = "0" * 64
SCHEMA_VERSION = "orq39-events-v1"

_EVENT_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEYS = {"schema_version", "seq", "type", "payload", "previous", "hash"}


class EventLogError(RuntimeError):
    """The log is missing, malformed, or its chain does not verify."""


def canonical_bytes(value: Any) -> bytes:
    """The one serialization every digest in this experiment is taken over."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_hex(Path(path).read_bytes())


def _event_hash(schema_version: str, seq: int, event_type: str, payload: Any, previous: str) -> str:
    return sha256_hex(
        canonical_bytes(
            {
                "schema_version": schema_version,
                "seq": seq,
                "type": event_type,
                "payload": payload,
                "previous": previous,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class Event:
    seq: int
    type: str
    payload: Mapping[str, Any]
    previous: str
    hash: str


def _parse(line: str, line_no: int) -> Event:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EventLogError(f"line {line_no}: not JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise EventLogError(f"line {line_no}: unexpected keys")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise EventLogError(f"line {line_no}: unknown schema_version")
    seq, event_type, payload = raw["seq"], raw["type"], raw["payload"]
    previous, digest = raw["previous"], raw["hash"]
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise EventLogError(f"line {line_no}: seq is not an integer")
    if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
        raise EventLogError(f"line {line_no}: invalid event type")
    if not isinstance(payload, dict):
        raise EventLogError(f"line {line_no}: payload is not an object")
    if not isinstance(previous, str) or not _SHA256.fullmatch(previous):
        raise EventLogError(f"line {line_no}: invalid previous hash")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise EventLogError(f"line {line_no}: invalid hash")
    return Event(seq=seq, type=event_type, payload=payload, previous=previous, hash=digest)


def verify(path: Path) -> tuple[Event, ...]:
    """Every event, in chain order, after recomputing the entire chain.

    A missing file is an empty chain: nothing has been recorded yet, which is
    distinct from a corrupt one. Anything else that does not verify raises.
    """
    path = Path(path)
    if not path.exists():
        return ()
    events: list[Event] = []
    expected_previous = GENESIS_PREVIOUS
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise EventLogError(f"line {line_no}: truncated write")
            event = _parse(line, line_no)
            if event.seq != len(events):
                raise EventLogError(f"line {line_no}: sequence gap")
            if event.previous != expected_previous:
                raise EventLogError(f"line {line_no}: chain broken")
            recomputed = _event_hash(
                SCHEMA_VERSION, event.seq, event.type, event.payload, event.previous
            )
            if recomputed != event.hash:
                raise EventLogError(f"line {line_no}: hash mismatch")
            events.append(event)
            expected_previous = event.hash
    return tuple(events)


def append(path: Path, event_type: str, payload: Mapping[str, Any]) -> Event:
    """Verify the existing chain, then durably append one event.

    The whole read-verify-write runs under an exclusive lock, so two writers
    cannot both extend the same predecessor.
    """
    if not _EVENT_TYPE.fullmatch(event_type):
        raise EventLogError("invalid event type")
    payload = json.loads(canonical_bytes(dict(payload)))  # JSON-safe, detached copy
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            events = verify(path)
            seq = len(events)
            previous = events[-1].hash if events else GENESIS_PREVIOUS
            digest = _event_hash(SCHEMA_VERSION, seq, event_type, payload, previous)
            record = {
                "schema_version": SCHEMA_VERSION,
                "seq": seq,
                "type": event_type,
                "payload": payload,
                "previous": previous,
                "hash": digest,
            }
            handle.write(canonical_bytes(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return Event(seq=seq, type=event_type, payload=payload, previous=previous, hash=digest)


def first(events: Sequence[Event], predicate: Callable[[Event], bool]) -> Event | None:
    return next((event for event in events if predicate(event)), None)


def precedes(
    events: Sequence[Event],
    earlier: Callable[[Event], bool],
    later: Callable[[Event], bool],
) -> bool:
    """True iff an `earlier` event exists and comes before every `later` event.

    Vacuously true when no `later` event exists yet: the ordering obligation
    only binds once the later stage has started.
    """
    first_earlier = first(events, earlier)
    first_later = first(events, later)
    if first_later is None:
        return first_earlier is not None
    return first_earlier is not None and first_earlier.seq < first_later.seq
