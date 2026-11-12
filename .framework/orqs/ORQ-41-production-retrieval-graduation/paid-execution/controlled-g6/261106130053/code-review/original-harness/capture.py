"""Local-only C1 capture and fail-closed validation; no network clients are created."""
from __future__ import annotations

import copy
import json
from collections import Counter

from app.core.observability import context_evidence as c1


class EvidenceError(ValueError):
    pass


class Capture:
    """Store serialized bodies in test memory only, never authorization headers."""
    def __init__(self):
        self.bodies = []
        self.sends = []

    def sent(self, body, *, adapter, application_attempt=None, sdk_attempt=None):
        application_attempt = _application_attempt.get() if application_attempt is None else application_attempt
        sdk_attempt = _sdk_attempt.get() if sdk_attempt is None else sdk_attempt
        raw = body.encode() if isinstance(body, str) else bytes(body)
        self.bodies.append(raw)
        data = json.loads(raw)
        if adapter == "bedrock":
            messages = [("system", block["text"]) for block in data.get("system", [])]
            messages += [(m["role"], "".join(b["text"] for b in m["content"]))
                         for m in data["messages"]]
        elif adapter == "openai":
            messages = [(m["role"], "".join(b["text"] for b in m["content"]))
                        for m in data["input"]]
        else:
            raise EvidenceError("unknown adapter")
        data = dict(
            send_ordinal=len(self.bodies) - 1,
            adapter=adapter, application_attempt=application_attempt, sdk_attempt=sdk_attempt,
            payload_sha256=c1.digest(raw), payload_bytes=len(raw),
            items=[c1.text_receipt(i, text, role=role) for i, (role, text) in enumerate(messages)])
        # This authoritative send record precedes, and is independent of, the
        # best-effort observer. A lost observation cannot remove an actual send.
        state = c1._current.get()
        self.sends.append(dict(
            instance_id=state.instance_id if state is not None else None,
            correlation_id=state.correlation_id if state is not None else None,
            invocation=c1._invocation.get(), purpose=c1._purpose.get(),
            **copy.deepcopy(data)))
        c1.observe("transport.dispatched", lambda _: copy.deepcopy(data))


def validate(snapshot, *, expected_instance_id, expected_correlation_id,
             expected_stages, expected_invocations, expected_messages,
             expected_data, expected_request_outcome, expected_invocation_outcomes,
             expected_purposes, transport_capture, expected_rendered_messages=None,
             expected_pre_dispatch_failures=None):
    """The independent case oracle is mandatory, including full stage data.

    expected_messages maps invocation IDs to ordered (role, text) pairs. An empty
    mapping is explicit no-dispatch evidence, never inferred from missing captures.
    expected_data maps ordinals to exact independently expected stage projections.
    Terminal outcomes and purposes are mandatory case expectations. The separate
    transport capture is mandatory even for a case expecting no dispatch.
    Explicit rendered messages may differ in membership from expected_messages
    only for prospectively declared pre-dispatch failures. Omitted render
    expectations preserve the existing shared render/delivery contract.
    """
    if (expected_request_outcome not in ("returned", "aborted")
            or not isinstance(expected_invocations, list)
            or any(not _positive_id(i) for i in expected_invocations)
            or len(set(expected_invocations)) != len(expected_invocations)):
        raise EvidenceError("invalid lifecycle oracle")
    for mapping in (expected_invocation_outcomes, expected_purposes):
        if (not isinstance(mapping, dict) or any(not _positive_id(i) for i in mapping)
                or set(mapping) != set(expected_invocations)):
            raise EvidenceError("incomplete invocation oracle")
    if (any(not isinstance(value, str) or not value for value in expected_invocation_outcomes.values())
            or any(value not in ("primary", "rewrite", "evaluator") for value in expected_purposes.values())):
        raise EvidenceError("invalid invocation oracle")
    if (not isinstance(expected_messages, dict)
            or any(not _positive_id(i) for i in expected_messages)
            or not set(expected_messages).issubset(expected_invocations)):
        raise EvidenceError("invalid delivery oracle identities")
    separate_render = expected_rendered_messages is not None
    rendered_messages = expected_rendered_messages if separate_render else expected_messages
    failures = {} if expected_pre_dispatch_failures is None else expected_pre_dispatch_failures
    for mapping in (rendered_messages, failures):
        if (not isinstance(mapping, dict) or any(not _positive_id(i) for i in mapping)
                or not set(mapping).issubset(expected_invocations)):
            raise EvidenceError("invalid render/failure oracle identities")
    render_only = set(rendered_messages) - set(expected_messages)
    if (set(failures) != render_only or (failures and not separate_render)
            or any(not isinstance(value, str) or not value or value == "returned"
                   or value != expected_invocation_outcomes[i] for i, value in failures.items())):
        raise EvidenceError("render-only invocation requires explicit pre-dispatch failure")
    if separate_render and not set(expected_messages).issubset(rendered_messages):
        raise EvidenceError("dispatch oracle lacks rendered expectation")
    if any(rendered_messages[i] != expected_messages[i]
           for i in set(rendered_messages) & set(expected_messages)):
        raise EvidenceError("contradictory render/dispatch expectations")
    if not isinstance(transport_capture, Capture):
        raise EvidenceError("missing authoritative transport capture")
    if not snapshot or not snapshot["valid"] or not snapshot["closed"]:
        raise EvidenceError("missing/invalid/unclosed request")
    identity = dict(instance_id=expected_instance_id, correlation_id=expected_correlation_id)
    if any(snapshot[k] != v for k, v in identity.items()):
        raise EvidenceError("wrong request identity")
    records = snapshot["records"]
    if not records or snapshot["count"] != len(records):
        raise EvidenceError("incomplete receipt")
    previous = "0" * 64
    for index, row in enumerate(records):
        value = {k: v for k, v in row.items() if k != "hash"}
        if row["ordinal"] != index or row["previous"] != previous or c1.digest(c1.encoded(value)) != row["hash"]:
            raise EvidenceError("corrupt/reordered receipt")
        previous = row["hash"]
    stages = [r["stage"] for r in records]
    if stages != expected_stages or stages[0] != "request.start" or stages[-1] != "request.end":
        raise EvidenceError("missing/duplicate/unexpected stage")
    if records[0]["data"] != identity:
        raise EvidenceError("contradictory request identity")
    end = records[-1]["data"]
    if (end["checkpoints"] != stages[:-1] or not end["valid"]
            or end.get("outcome") != expected_request_outcome):
        raise EvidenceError("contradictory completion")
    starts = [r["invocation"] for r in records if r["stage"] == "invocation.start"]
    finishes = [r["invocation"] for r in records if r["stage"] == "invocation.end"]
    if starts != expected_invocations or Counter(finishes) != Counter(starts) or len(set(starts)) != len(starts):
        raise EvidenceError("invalid invocation lifecycle")
    if end["invocations"] != len(starts):
        raise EvidenceError("incomplete invocation summary")
    if any(not _positive_id(i) for i in starts + finishes):
        raise EvidenceError("invalid invocation identity")
    active = set()
    dispatched = set()
    rendered = set()
    attempts = set()
    for row in records:
        name, invocation = row["stage"], row["invocation"]
        if invocation is not None:
            if (not _positive_id(invocation) or invocation not in expected_purposes
                    or row["purpose"] != expected_purposes[invocation]):
                raise EvidenceError("invalid invocation identity/purpose")
            if name != "invocation.start" and invocation not in active:
                raise EvidenceError("record outside active invocation")
        if name == "invocation.start":
            active.add(invocation)
        elif name == "invocation.end":
            if invocation not in active:
                raise EvidenceError("out of order invocation")
            if row["data"].get("outcome") != expected_invocation_outcomes[invocation]:
                raise EvidenceError("unexpected invocation disposition")
            active.remove(invocation)
        elif name in ("transport.dispatched", "prompt.rendered"):
            if invocation not in active:
                raise EvidenceError("uncorrelated dispatch/render")
            messages = rendered_messages if name == "prompt.rendered" else expected_messages
            if invocation not in messages:
                raise EvidenceError("unexpected dispatch/render")
            wanted = [c1.text_receipt(i, text, role=role)
                      for i, (role, text) in enumerate(messages[invocation])]
            if row["data"]["items"] != wanted:
                raise EvidenceError("serialized/rendered payload disagrees with oracle")
            if name == "transport.dispatched":
                if separate_render and invocation not in rendered:
                    raise EvidenceError("dispatch precedes render")
                if any(not _positive_id(row["data"].get(key))
                       for key in ("application_attempt", "sdk_attempt")):
                    raise EvidenceError("invalid transport attempt identity")
                key = (invocation, row["data"]["application_attempt"], row["data"]["sdk_attempt"])
                if key in attempts:
                    raise EvidenceError("duplicate transport attempt")
                attempts.add(key)
                dispatched.add(invocation)
            else:
                if invocation in rendered:
                    raise EvidenceError("duplicate render")
                rendered.add(invocation)
        if row["ordinal"] in expected_data and row["data"] != expected_data[row["ordinal"]]:
            raise EvidenceError("stage identity/span/scope mismatch")
    # Every non-lifecycle/non-transport stage requires independent expected data.
    checked = {"request.start", "request.end", "invocation.start", "invocation.end",
               "prompt.rendered", "transport.dispatched"}
    if any(r["ordinal"] not in expected_data for r in records if r["stage"] not in checked):
        raise EvidenceError("missing stage oracle")
    if dispatched != set(expected_messages):
        raise EvidenceError("missing serialized delivery")
    if separate_render and rendered != set(rendered_messages):
        raise EvidenceError("missing rendered prompt")
    _reconcile_transport(transport_capture, records, identity)
    return True


def _positive_id(value):
    return type(value) is int and value >= 1


def _reconcile_transport(capture, records, identity):
    dispatches = [r for r in records if r["stage"] == "transport.dispatched"]
    if len(capture.bodies) != len(capture.sends) or len(capture.sends) != len(dispatches):
        raise EvidenceError("transport/receipt count mismatch")
    for ordinal, (raw, send, row) in enumerate(zip(capture.bodies, capture.sends, dispatches)):
        if any(not _positive_id(send.get(key))
               for key in ("invocation", "application_attempt", "sdk_attempt")):
            raise EvidenceError("invalid authoritative transport identity")
        if (type(send.get("send_ordinal")) is not int or send["send_ordinal"] != ordinal
                or type(row["data"].get("send_ordinal")) is not int
                or row["data"]["send_ordinal"] != ordinal):
            raise EvidenceError("transport order mismatch")
        if (send.get("payload_sha256") != c1.digest(raw)
                or send.get("payload_bytes") != len(raw)):
            raise EvidenceError("transport body integrity mismatch")
        if send != dict(**identity, invocation=row["invocation"], purpose=row["purpose"], **row["data"]):
            raise EvidenceError("transport/receipt identity or payload mismatch")


# Scoped to the local serial harness, not installed by the application.
from contextlib import contextmanager
from contextvars import ContextVar
import logging

_application_attempt = ContextVar("capture_application_attempt", default=1)
_sdk_attempt = ContextVar("capture_sdk_attempt", default=1)


@contextmanager
def application_attempts():
    """Read existing structured log records, never count logical calls."""
    class Attempts(logging.Handler):
        def emit(self, record):
            if record.getMessage() == "provider.request":
                _application_attempt.set(record.attempt)
                _sdk_attempt.set(1)
    handler = Attempts()
    loggers = [logging.getLogger("app.core.providers." + name)
               for name in ("bedrock_provider", "openai_provider")]
    app_token = _application_attempt.set(1)
    sdk_token = _sdk_attempt.set(1)
    for logger in loggers:
        logger.addHandler(handler)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
        _application_attempt.reset(app_token)
        _sdk_attempt.reset(sdk_token)


def sdk_attempts(client):
    """Bind SDK's explicit HTTP attempt field at its existing signing seam."""
    def before_sign(request, **kwargs):
        _sdk_attempt.set(request.context["retries"]["attempt"])
    client.meta.events.register("before-sign.bedrock-runtime", before_sign)
