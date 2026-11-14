"""Local request-scoped retry receipt; never participates in retry decisions."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging


@dataclass
class RetryEvidence:
    retry_announced: bool = False
    evidence_valid: bool = True

    def announce(self):
        self.retry_announced = True


_current: ContextVar[RetryEvidence | None] = ContextVar("retry_evidence", default=None)


def announce():
    """Record before logging, sharing the mutable receipt with child tasks."""
    state = _current.get()
    if state is not None:
        try:
            state.announce()
        except Exception:
            state.evidence_valid = False


@contextmanager
def request_evidence(request_id):
    state = None
    token = None
    try:
        state = RetryEvidence()
        token = _current.set(state)
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            logging.getLogger(__name__).info(
                "campaign.retry_summary request_id=%s retry_announced=%s evidence_valid=%s",
                request_id,
                "true" if state and state.retry_announced else "false",
                "true" if token is not None and state.evidence_valid else "false",
            )
        except Exception:
            pass
        finally:
            if token is not None:
                _current.reset(token)
