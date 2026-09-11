from __future__ import annotations

from contextvars import ContextVar
import uuid
from typing import Optional
from uuid import UUID

_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

# --- ORQ-37 T8: telemetry identity, server-generated -------------------------
#
# `request_id` above is accepted from the inbound `X-Request-ID` verbatim, so it
# is **client-controlled**: arbitrary, oversized or control-character content
# can reach anything that reads it. It is left exactly as it is -- existing
# consumers and response headers depend on it, and changing it is not this
# ORQ's business.
#
# What telemetry uses instead is minted here and never comes from a header:
#
#   `request_instance_id`  a uuid4 per request, ALWAYS present. This is
#                          identity: spans and metrics rows carry it.
#   `telemetry_correlation_id`  the inbound X-Request-ID, but only when it
#                          passed validation. Correlation metadata, never
#                          identity, and None when the header was absent or
#                          rejected.
#
# NOTE the near-collision: `_correlation_id_var` above comes from a *different*
# header (`X-Correlation-ID`) and defaults to `request_id`. The two are not
# interchangeable, and conflating them would silently make client-controlled
# text an identity again -- which is the whole point of this split.
_request_instance_id_var: ContextVar[Optional[str]] = ContextVar(
    "request_instance_id", default=None
)
_telemetry_correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "telemetry_correlation_id", default=None
)

# A UUID's canonical form is exactly 36 characters. The length bound is stated
# separately from the parse because it is what stops a megabyte of text from
# reaching the parser at all.
_MAX_CORRELATION_LEN = 36


def validate_correlation_id(raw: Optional[str]) -> Optional[str]:
    """Return the inbound value only if it is a well-formed UUID, else None.

    Dropped **entirely** -- never truncated, never sanitized into some other
    form, never emitted alongside a `_invalid` marker. A partially-accepted
    value is still attacker-shaped, and an allow-list over attribute *keys*
    cannot constrain attribute *values*.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > _MAX_CORRELATION_LEN:
        return None
    try:
        parsed = UUID(candidate)
    except (ValueError, AttributeError, TypeError):
        return None
    # Re-render from the parsed value: `UUID` accepts braces, urn: prefixes and
    # missing hyphens, so echoing the raw string would let a non-canonical
    # spelling through under a validated name.
    return str(parsed)


def set_telemetry_identity(
    request_instance_id: str, correlation_id: Optional[str]
) -> tuple[object, object]:
    t1 = _request_instance_id_var.set(request_instance_id)
    t2 = _telemetry_correlation_id_var.set(correlation_id)
    return t1, t2


def reset_telemetry_identity(t1: object, t2: object) -> None:
    _request_instance_id_var.reset(t1)  # type: ignore[arg-type]
    _telemetry_correlation_id_var.reset(t2)  # type: ignore[arg-type]


def get_request_instance_id() -> Optional[str]:
    """The server-generated per-request identity. Never client-controlled."""
    return _request_instance_id_var.get()


def get_telemetry_correlation_id() -> Optional[str]:
    """The validated inbound X-Request-ID, or None. Correlation, not identity."""
    return _telemetry_correlation_id_var.get()


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


def request_uuid() -> uuid.UUID:
    """A UUID derived from the inbound request id, or a fresh one.

    `get_request_id()` returns the inbound `X-Request-ID` **verbatim**:
    `RequestContextMiddleware` decodes it with ``errors="replace"``, strips it
    and says so in its own comment -- "may be arbitrary client text". AC25
    documents that as deliberate; the header is correlation metadata, taken as
    sent.

    Three call sites nonetheless did ``uuid.UUID(rid)`` outside any
    degradation boundary -- `chat.py`'s route body, and both
    `get_chat_memory_context` and `get_chat_rag_context` before their `try`.
    A header of ``not-a-uuid`` therefore answered **500 on every /chat
    request**, on both paths, with both feature flags off (N-1).

    A malformed value is **dropped** and a fresh UUID minted, the same rule
    `validate_correlation_id` already applies to the telemetry correlation id
    (AC32). What this does NOT do is sanitise the client's string: the header
    keeps travelling verbatim in the context var and in the response headers,
    because that is AC25's decision and this helper is not the place to
    revisit it.
    """
    rid = _request_id_var.get()
    if rid:
        try:
            return uuid.UUID(rid)
        except (ValueError, AttributeError, TypeError):
            pass
    return uuid.uuid4()


def get_correlation_id() -> Optional[str]:
    return _correlation_id_var.get()
