from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def set_request_context(request_id: str, correlation_id: str) -> tuple[object, object]:
    """
    Set request-scoped IDs. Returns tokens to allow reset().
    """
    t1 = _request_id_var.set(request_id)
    t2 = _correlation_id_var.set(correlation_id)
    return t1, t2


def reset_request_context(t1: object, t2: object) -> None:
    _request_id_var.reset(t1)  # type: ignore[arg-type]
    _correlation_id_var.reset(t2)  # type: ignore[arg-type]


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def get_correlation_id() -> Optional[str]:
    return _correlation_id_var.get()
