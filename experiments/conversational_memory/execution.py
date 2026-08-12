from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
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
