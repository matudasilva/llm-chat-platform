"""Connect offline planning and reservations using a deterministic fake only.

This is a test harness, not a live execution path. It cannot dispatch to a
provider and does not persist responses. A crashed run is never resumed.
"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from .ledger import ReservationLedger
from .runner import AdmissionError, Manifest, VerifiedCounter, preflight


class SimulatedCrash(BaseException):
    """Simulate process loss after the dispatch marker is durable."""


@dataclass(frozen=True)
class FakeResult:
    call_id: str
    payload_sha256: str
    output: str


class FakeDispatcher:
    """In-memory scripted outcomes; this class contains no transport."""

    def __init__(self, outcomes: tuple[str, ...] = ()):
        if type(outcomes) is not tuple or any(x not in ('ok', 'error', 'crash') for x in outcomes):
            raise ValueError('invalid fake outcomes')
        self.outcomes = outcomes
        self.dispatched: list[str] = []

    def dispatch(self, call_id: str, payload: bytes, digest: str) -> FakeResult:
        if sha256(payload).hexdigest() != digest:
            raise AdmissionError('payload changed before dispatch')
        self.dispatched.append(call_id)
        index = len(self.dispatched) - 1
        outcome = self.outcomes[index] if index < len(self.outcomes) else 'ok'
        if outcome == 'crash':
            raise SimulatedCrash()
        if outcome == 'error':
            raise RuntimeError('simulated dispatch failure')
        return FakeResult(call_id, digest, 'synthetic output')


def run_offline(manifest: Manifest, counter: VerifiedCounter, ledger: ReservationLedger,
                dispatcher: FakeDispatcher, *, now: datetime) -> tuple[FakeResult, ...]:
    """Reserve the complete plan, then consume each call exactly once.

    Existing run IDs are always rejected by the ledger; this function never
    resumes pending or ambiguous calls. The exact fake type is mandatory.
    """
    if type(dispatcher) is not FakeDispatcher:
        raise TypeError('only the built-in fake dispatcher is permitted')
    plan = preflight(manifest, counter, now=now)
    ledger.admit(plan.run_id, plan.manifest_sha256, plan.reservation_usd,
                 (call.call_id for call in plan.calls))
    results = []
    for call in plan.calls:
        ledger.mark_dispatching(plan.run_id, call.call_id)
        try:
            result = dispatcher.dispatch(call.call_id, call.payload, call.payload_sha256)
        except Exception:
            ledger.record_outcome(plan.run_id, call.call_id, succeeded=False)
            raise
        ledger.record_outcome(plan.run_id, call.call_id, succeeded=True)
        results.append(result)
    ledger.finish_run(plan.run_id)
    return tuple(results)
