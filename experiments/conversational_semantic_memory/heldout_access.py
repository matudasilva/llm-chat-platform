"""Audited held-out reads; direct filesystem access outside this module is not policed."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from . import events, paths


class HeldoutSealError(RuntimeError):
    """No trusted sealed bytes can be supplied to the caller."""


def _path_key(pool_path: Path) -> str:
    """Repo-relative when possible, so a moved checkout still finds its seal
    and no absolute local path is written into evidence."""
    resolved = Path(pool_path).resolve()
    try:
        return resolved.relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _sealed_digest(pool_path: Path, events_log: Path) -> str:
    matching = [event for event in events.verify(events_log)
                if event.type == "heldout_pool_sealed"
                and event.payload.get("pool_path") == _path_key(pool_path)]
    if len(matching) != 1:
        raise HeldoutSealError("exactly one seal is required")
    digest = matching[0].payload.get("sha256")
    if not isinstance(digest, str):
        raise HeldoutSealError("missing sealed digest")
    return digest


def seal(pool_path: Path = paths.HELDOUT_POOL, *,
         events_log: Path = paths.EVENTS_LOG) -> events.Event:
    """Seal once; a later seal cannot legitimize modified pool contents."""
    pool_path = Path(pool_path).resolve()
    if any(event.type == "heldout_pool_sealed"
           and event.payload.get("pool_path") == _path_key(pool_path)
           for event in events.verify(events_log)):
        raise HeldoutSealError("pool is already sealed")
    return events.append(events_log, "heldout_pool_sealed", {
        "pool_path": _path_key(pool_path), "sha256": events.file_sha256(pool_path),
    })


def _read(pool_path: Path, events_log: Path, purpose: str) -> bytes:
    pool_path = Path(pool_path).resolve()
    expected = _sealed_digest(pool_path, events_log)
    data = pool_path.read_bytes()
    digest = events.sha256_hex(data)
    # Log failed digest checks as well; return only the exact bytes hashed here.
    events.append(events_log, "heldout_pool_access", {
        "pool_path": _path_key(pool_path), "purpose": purpose, "sha256": digest,
        "sealed_sha256": expected, "matches_seal": digest == expected,
    })
    if digest != expected:
        raise HeldoutSealError("held-out pool digest differs from its seal")
    return data


def read_metadata(extract: Callable[[bytes], Mapping[str, int]],
                  pool_path: Path = paths.HELDOUT_POOL, *,
                  events_log: Path = paths.EVENTS_LOG) -> dict[str, int]:
    """Expose only numeric aggregates, with the pool schema owned by the caller."""
    metadata = dict(extract(_read(pool_path, events_log, "metadata")))
    if any(not isinstance(key, str) or type(value) is not int or value < 0
           for key, value in metadata.items()):
        raise HeldoutSealError("metadata must contain non-negative integer aggregates")
    return metadata


def read_for_scan(pool_path: Path = paths.HELDOUT_POOL, *,
                  events_log: Path = paths.EVENTS_LOG) -> bytes:
    return _read(pool_path, events_log, "fixture_scan")


def verify_seal(pool_path: Path = paths.HELDOUT_POOL, *,
                events_log: Path = paths.EVENTS_LOG) -> str:
    """Re-read and audit the digest immediately before T6 instantiation."""
    return events.sha256_hex(_read(pool_path, events_log, "verify_seal"))


def assert_not_heldout_path(path: Path, *, heldout_path: Path = paths.HELDOUT_POOL) -> None:
    """The dev runner must call this before opening any candidate input path."""
    candidate, heldout = Path(path).resolve(), Path(heldout_path).resolve()
    if candidate == heldout or (candidate.exists() and heldout.exists()
                                and candidate.samefile(heldout)):
        raise HeldoutSealError("dev runner cannot open the held-out pool")
