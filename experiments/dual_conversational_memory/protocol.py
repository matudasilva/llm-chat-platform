from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PACKAGE / "development-manifest.json"
ALLOWED_SPLITS = {"authoring", "development"}
EXTERNAL_KINDS = {"generation", "semantic_extraction", "embedding_batch"}


class ProtocolError(RuntimeError):
    """The approved development protocol cannot be followed safely."""


class BudgetExceeded(ProtocolError):
    """An approved external-call limit would be exceeded."""


class TraceabilityError(ProtocolError):
    """The append-only external-call ledger is inconsistent."""


@dataclass(frozen=True, slots=True)
class FrozenManifest:
    path: Path
    payload: Mapping[str, Any]
    sha256: str

    @property
    def call_limits(self) -> Mapping[str, int]:
        return self.payload["external_call_limits"]

    @property
    def expected_commit(self) -> str:
        return str(self.payload["origin"]["expected_commit"])


@dataclass(frozen=True, slots=True)
class CallReservation:
    call_id: str
    kind: str
    model: str
    step_id: str | None
    arm: str | None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> FrozenManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError("development manifest is unavailable or invalid") from exc
    if payload.get("schema_version") != "orq29-development-manifest-v1":
        raise ProtocolError("development manifest schema is invalid")
    if payload.get("status") != "frozen_operator_approved":
        raise ProtocolError("development manifest is not operator-approved")
    heldout = payload.get("heldout")
    if heldout != {
        "bundle": None,
        "hash": None,
        "path": None,
        "seed": None,
        "status": "not_generated_not_accessible",
    }:
        raise ProtocolError("held-out fields must remain null and inaccessible")
    limits = payload.get("external_call_limits")
    if limits != {
        "embedding_batch": 120,
        "generation": 528,
        "semantic_extraction": 144,
        "total": 792,
    }:
        raise ProtocolError("external-call limits differ from operator approval")
    if payload.get("generation", {}).get("repetitions") != 1:
        raise ProtocolError("development repetitions are frozen at one")
    if payload.get("execution") != {
        "embedding_batch_size": 128,
        "external_timeout_seconds": 60,
        "generation_concurrency": 4,
        "semantic_extraction_concurrency": 1,
    }:
        raise ProtocolError("development execution controls differ from the frozen plan")
    if payload.get("protocol", {}).get("candidate_profiles_maximum") != 30:
        raise ProtocolError("development candidate-profile ceiling differs from approval")
    return FrozenManifest(path=path, payload=payload, sha256=sha256_file(path))


def require_allowed_split(split: str) -> None:
    if split not in ALLOWED_SPLITS:
        raise ProtocolError(
            "held-out generation and access are blocked until final pre-registration"
        )


def verify_origin(manifest: FrozenManifest) -> dict[str, Any]:
    expected = manifest.expected_commit
    fetch = subprocess.run(
        ["git", "fetch", "origin"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode:
        raise ProtocolError("origin fetch failed before external execution")
    refs = {
        "head": _git_output("rev-parse", "HEAD"),
        "main": _git_output("rev-parse", "main"),
        "origin_main": _git_output("rev-parse", "origin/main"),
        "origin_orq29": _git_output(
            "rev-parse", "origin/orq/ORQ-29-dual-conversational-memory"
        ),
        "reservation_tag": _git_output(
            "rev-parse", "refs/tags/ait-orq-number-ORQ-29"
        ),
        "remote_reservation_tag": _remote_ref_commit(
            "refs/tags/ait-orq-number-ORQ-29"
        ),
    }
    if any(value != expected for value in refs.values()):
        raise ProtocolError(f"origin alignment differs from approved commit: {refs}")
    divergence = _git_output("rev-list", "--left-right", "--count", "origin/main...HEAD")
    if divergence != "0\t0":
        raise ProtocolError(f"origin/main divergence is not zero: {divergence}")
    return {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "expected_commit": expected,
        "refs": refs,
        "divergence": divergence,
    }


def instrument_hashes(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(ROOT)
        except ValueError as exc:
            raise ProtocolError("instrument path is outside repository") from exc
        if not resolved.is_file():
            raise ProtocolError(f"instrument path is unavailable: {relative}")
        result[str(relative)] = sha256_file(resolved)
    return result


class ExternalCallLedger:
    """Content-free append-only ledger with hard per-kind and total limits."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        manifest: FrozenManifest,
        origin_attestation: Mapping[str, Any],
    ) -> None:
        self.path = path
        self.run_id = run_id
        self.manifest = manifest
        self.origin_attestation = origin_attestation
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._validate_trace()

    def reserve(
        self,
        *,
        kind: str,
        model: str,
        step_id: str | None = None,
        arm: str | None = None,
    ) -> CallReservation:
        if kind not in EXTERNAL_KINDS:
            raise TraceabilityError(f"unknown external-call kind {kind!r}")
        if self.origin_attestation.get("expected_commit") != self.manifest.expected_commit:
            raise TraceabilityError("origin attestation does not match manifest")
        counts = self.counts()
        kind_limit = int(self.manifest.call_limits[kind])
        total_limit = int(self.manifest.call_limits["total"])
        if counts[kind] >= kind_limit or counts["total"] >= total_limit:
            self._append(
                {
                    "event": "budget_blocked",
                    "kind": kind,
                    "model": model,
                    "step_id": step_id,
                    "arm": arm,
                    "call_id": None,
                    "reason": "approved_external_call_limit_reached",
                }
            )
            raise BudgetExceeded(
                f"external-call limit reached for {kind}: {counts[kind]}/{kind_limit}, "
                f"total {counts['total']}/{total_limit}"
            )
        call = CallReservation(str(uuid4()), kind, model, step_id, arm)
        self._append(
            {
                "event": "started",
                "kind": kind,
                "model": model,
                "step_id": step_id,
                "arm": arm,
                "call_id": call.call_id,
                "reason": None,
            }
        )
        return call

    def succeeded(
        self,
        call: CallReservation,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_tokens: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        self._terminal(
            call,
            event="succeeded",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_tokens=estimated_tokens,
            duration_ms=duration_ms,
            error_kind=None,
        )

    def failed(
        self,
        call: CallReservation,
        *,
        error_kind: str,
        duration_ms: float | None = None,
    ) -> None:
        self._terminal(
            call,
            event="failed",
            input_tokens=None,
            output_tokens=None,
            estimated_tokens=None,
            duration_ms=duration_ms,
            error_kind=error_kind,
        )

    def counts(self) -> dict[str, int]:
        events = self._events()
        started = [event for event in events if event["event"] == "started"]
        return {
            kind: sum(event["kind"] == kind for event in started)
            for kind in sorted(EXTERNAL_KINDS)
        } | {"total": len(started)}

    def summary(self) -> dict[str, Any]:
        events = self._events()
        started = {event["call_id"]: event for event in events if event["event"] == "started"}
        terminals = {
            event["call_id"]: event
            for event in events
            if event["event"] in {"succeeded", "failed"}
        }
        return {
            "counts": self.counts(),
            "succeeded": sum(event["event"] == "succeeded" for event in events),
            "failed": sum(event["event"] == "failed" for event in events),
            "unknown_outcome": len(set(started) - set(terminals)),
            "input_tokens": sum(int(event.get("input_tokens") or 0) for event in terminals.values()),
            "output_tokens": sum(int(event.get("output_tokens") or 0) for event in terminals.values()),
            "estimated_embedding_tokens": sum(
                int(event.get("estimated_tokens") or 0)
                for event in terminals.values()
                if event["kind"] == "embedding_batch"
            ),
            "duration_ms_by_kind": {
                kind: [
                    float(event["duration_ms"])
                    for event in terminals.values()
                    if event["kind"] == kind and event.get("duration_ms") is not None
                ]
                for kind in sorted(EXTERNAL_KINDS)
            },
        }

    def _terminal(self, call: CallReservation, **fields: Any) -> None:
        events = self._events()
        starts = [event for event in events if event.get("call_id") == call.call_id and event["event"] == "started"]
        terminals = [event for event in events if event.get("call_id") == call.call_id and event["event"] in {"succeeded", "failed"}]
        if len(starts) != 1 or terminals:
            raise TraceabilityError("external-call terminal state is inconsistent")
        self._append(
            {
                "kind": call.kind,
                "model": call.model,
                "step_id": call.step_id,
                "arm": call.arm,
                "call_id": call.call_id,
                "reason": None,
                **fields,
            }
        )

    def _validate_trace(self) -> None:
        events = self._events()
        starts: dict[str, dict[str, Any]] = {}
        terminals: set[str] = set()
        for event in events:
            call_id = event.get("call_id")
            if event["event"] == "started":
                if not call_id or call_id in starts:
                    raise TraceabilityError("duplicate or missing call reservation")
                starts[call_id] = event
            elif event["event"] in {"succeeded", "failed"}:
                if call_id not in starts or call_id in terminals:
                    raise TraceabilityError("orphan or duplicate call terminal")
                terminals.add(call_id)
        if set(starts) - terminals:
            raise TraceabilityError("an earlier external call has unknown outcome")

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            rows = [
                json.loads(line)
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceabilityError("external-call ledger cannot be parsed") from exc
        for row in rows:
            if not isinstance(row, dict) or row.get("schema_version") != "orq29-external-call-ledger-v1":
                raise TraceabilityError("external-call ledger schema is invalid")
            if row.get("manifest_sha256") != self.manifest.sha256:
                raise TraceabilityError("external-call ledger manifest hash mismatch")
            if row.get("origin_commit") != self.manifest.expected_commit:
                raise TraceabilityError("external-call ledger origin commit mismatch")
        return rows

    def _append(self, fields: Mapping[str, Any]) -> None:
        row = {
            "schema_version": "orq29-external-call-ledger-v1",
            "event_id": str(uuid4()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "manifest_sha256": self.manifest.sha256,
            "origin_commit": self.manifest.expected_commit,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ProtocolError(f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _remote_ref_commit(ref: str) -> str:
    output = _git_output("ls-remote", "origin", ref)
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise ProtocolError(f"origin ref {ref} is missing or ambiguous")
    return rows[0][0]
