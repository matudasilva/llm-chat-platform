from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ExecutionCall:
    call_id: str
    operation: str
    model: str
    step_id: str | None
    arm: str | None
    repetition: int | None


class ExecutionLedger:
    """Content-free append-only audit of potentially billable API calls."""

    def __init__(self, path: Path, *, run_id: str, phase: str) -> None:
        self._path = path
        self._run_id = run_id
        self._phase = phase
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def started(
        self,
        *,
        operation: str,
        model: str,
        step_id: str | None = None,
        arm: str | None = None,
        estimated_tokens: int | None = None,
        repetition: int | None = None,
    ) -> ExecutionCall:
        call = ExecutionCall(str(uuid4()), operation, model, step_id, arm, repetition)
        self._append(
            call,
            status="started",
            potentially_billable=True,
            estimated_tokens=estimated_tokens,
            actual_input_tokens=None,
            actual_output_tokens=None,
            error_kind=None,
        )
        return call

    def succeeded(
        self,
        call: ExecutionCall,
        *,
        estimated_tokens: int | None = None,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
    ) -> None:
        self._append(
            call,
            status="succeeded",
            potentially_billable=True,
            estimated_tokens=estimated_tokens,
            actual_input_tokens=actual_input_tokens,
            actual_output_tokens=actual_output_tokens,
            error_kind=None,
        )

    def failed(self, call: ExecutionCall, *, error_kind: str, potentially_billable: bool) -> None:
        self._append(
            call,
            status="failed",
            potentially_billable=potentially_billable,
            estimated_tokens=None,
            actual_input_tokens=None,
            actual_output_tokens=None,
            error_kind=error_kind,
        )

    def _append(self, call: ExecutionCall, **fields: Any) -> None:
        event = {
            "schema_version": "conversation-memory-execution-event-v1",
            "event_id": str(uuid4()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "phase": self._phase,
            "call_id": call.call_id,
            "operation": call.operation,
            "model": call.model,
            "step_id": call.step_id,
            "arm": call.arm,
            "repetition": call.repetition,
            **fields,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


class HeldoutAttemptError(RuntimeError):
    """Raised when the frozen held-out attempt policy forbids execution."""


@dataclass(frozen=True, slots=True)
class HeldoutAttempt:
    run_id: str
    attempt_number: int


class HeldoutAttemptLedger:
    """Content-free append-only state for the one-valid-run held-out policy."""

    _SCHEMA_VERSION = "conversation-memory-heldout-attempt-v1"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def start(
        self,
        *,
        run_id: str,
        registration_sha256: str,
        dataset_sha256: str,
        git_head: str,
        policy: Mapping[str, Any],
    ) -> HeldoutAttempt:
        max_total_attempts = _positive_int(policy, "maximum_total_attempts")
        maximum_replacements = _non_negative_int(
            policy, "maximum_replacement_attempts"
        )
        if max_total_attempts != maximum_replacements + 1:
            raise HeldoutAttemptError("held-out attempt limits are inconsistent")
        events = self._read_events()
        starts = [event for event in events if event["status"] == "started"]
        terminals = {
            event["run_id"]: event
            for event in events
            if event["status"] in {"invalid", "completed"}
        }
        if any(event["status"] == "completed" for event in events):
            raise HeldoutAttemptError("a valid held-out run already completed")
        if starts:
            last = starts[-1]
            terminal = terminals.get(last["run_id"])
            if terminal is None:
                raise HeldoutAttemptError(
                    "the previous held-out attempt has no terminal classification"
                )
            if terminal["status"] != "invalid" or not terminal["retry_eligible"]:
                raise HeldoutAttemptError(
                    "the previous held-out attempt does not authorize replacement"
                )
        attempt_number = len(starts) + 1
        if attempt_number > max_total_attempts:
            raise HeldoutAttemptError("the held-out attempt limit is exhausted")
        if any(event["run_id"] == run_id for event in events):
            raise HeldoutAttemptError("held-out run_id already exists")
        reservation_path = self._path.parent / (
            f"heldout-attempt-{attempt_number}.reserved"
        )
        try:
            with reservation_path.open("x", encoding="utf-8") as handle:
                handle.write(f"{run_id}\n")
        except FileExistsError as exc:
            raise HeldoutAttemptError(
                "the held-out attempt was already reserved"
            ) from exc
        event = {
            "schema_version": self._SCHEMA_VERSION,
            "event_id": str(uuid4()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "attempt_number": attempt_number,
            "status": "started",
            "registration_sha256": registration_sha256,
            "dataset_sha256": dataset_sha256,
            "git_head": git_head,
            "reason_code": None,
            "retry_eligible": None,
            "verdict": None,
        }
        self._append(event)
        return HeldoutAttempt(run_id=run_id, attempt_number=attempt_number)

    def invalid(
        self,
        attempt: HeldoutAttempt,
        *,
        reason_code: str,
        retry_eligible: bool,
    ) -> None:
        self._terminal(
            attempt,
            status="invalid",
            reason_code=reason_code,
            retry_eligible=retry_eligible,
            verdict=None,
        )

    def completed(self, attempt: HeldoutAttempt, *, verdict: str) -> None:
        if verdict not in {"GO", "NO_GO"}:
            raise HeldoutAttemptError("held-out verdict is invalid")
        self._terminal(
            attempt,
            status="completed",
            reason_code=None,
            retry_eligible=False,
            verdict=verdict,
        )

    def _terminal(
        self,
        attempt: HeldoutAttempt,
        *,
        status: str,
        reason_code: str | None,
        retry_eligible: bool,
        verdict: str | None,
    ) -> None:
        events = self._read_events()
        starts = [
            event
            for event in events
            if event["run_id"] == attempt.run_id and event["status"] == "started"
        ]
        terminals = [
            event
            for event in events
            if event["run_id"] == attempt.run_id and event["status"] != "started"
        ]
        if len(starts) != 1 or terminals:
            raise HeldoutAttemptError("held-out attempt terminal state is invalid")
        started = starts[0]
        self._append(
            {
                **started,
                "event_id": str(uuid4()),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "reason_code": reason_code,
                "retry_eligible": retry_eligible,
                "verdict": verdict,
            }
        )

    def _read_events(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            events = [
                json.loads(line)
                for line in self._path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise HeldoutAttemptError("held-out attempt ledger is invalid") from exc
        required = {
            "schema_version",
            "event_id",
            "recorded_at",
            "run_id",
            "attempt_number",
            "status",
            "registration_sha256",
            "dataset_sha256",
            "git_head",
            "reason_code",
            "retry_eligible",
            "verdict",
        }
        for event in events:
            if not isinstance(event, dict) or set(event) != required:
                raise HeldoutAttemptError("held-out attempt event schema is invalid")
            if event["schema_version"] != self._SCHEMA_VERSION:
                raise HeldoutAttemptError("held-out attempt schema version is invalid")
            if event["status"] not in {"started", "invalid", "completed"}:
                raise HeldoutAttemptError("held-out attempt status is invalid")
        starts = [event for event in events if event["status"] == "started"]
        if [event["attempt_number"] for event in starts] != list(
            range(1, len(starts) + 1)
        ):
            raise HeldoutAttemptError("held-out attempt numbering is invalid")
        return events

    def _append(self, event: Mapping[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _positive_int(values: Mapping[str, Any], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise HeldoutAttemptError(f"{key} must be a positive integer")
    return value


def _non_negative_int(values: Mapping[str, Any], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HeldoutAttemptError(f"{key} must be a non-negative integer")
    return value


def summarize_execution_ledger(path: Path, *, run_id: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {
            "started_calls": 0,
            "succeeded_calls": 0,
            "failed_calls": 0,
            "unknown_outcome_calls": 0,
            "potentially_billable_failures": 0,
            "estimated_embedding_tokens": 0,
            "actual_generation_input_tokens": 0,
            "actual_generation_output_tokens": 0,
            "missing_success_usage_calls": 0,
        }
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if run_id is not None:
        events = [event for event in events if event["run_id"] == run_id]
    by_call: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_call.setdefault(event["call_id"], []).append(event)
    terminal = {
        call_id: next(
            (event for event in reversed(call_events) if event["status"] != "started"),
            None,
        )
        for call_id, call_events in by_call.items()
    }
    completed = [event for event in terminal.values() if event is not None]
    successful = [event for event in completed if event["status"] == "succeeded"]
    failed = [event for event in completed if event["status"] == "failed"]
    return {
        "events": len(events),
        "started_calls": len(by_call),
        "succeeded_calls": len(successful),
        "failed_calls": len(failed),
        "unknown_outcome_calls": sum(event is None for event in terminal.values()),
        "potentially_billable_failures": sum(
            bool(event["potentially_billable"]) for event in failed
        ),
        "estimated_embedding_tokens": sum(
            int(event["estimated_tokens"] or 0)
            for event in successful
            if event["operation"] == "embedding"
        ),
        "actual_generation_input_tokens": sum(
            int(event["actual_input_tokens"] or 0)
            for event in successful
            if event["operation"] == "generation"
        ),
        "actual_generation_output_tokens": sum(
            int(event["actual_output_tokens"] or 0)
            for event in successful
            if event["operation"] == "generation"
        ),
        "missing_success_usage_calls": sum(
            event["operation"] == "generation"
            and (
                event["actual_input_tokens"] is None
                or event["actual_output_tokens"] is None
            )
            for event in successful
        ),
    }
