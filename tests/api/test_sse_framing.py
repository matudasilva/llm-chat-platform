from __future__ import annotations

import json

from app.api.routes.chat import _sse, _sse_json


def _reference_parse(wire: str) -> tuple[str, str]:
    """Minimal reference SSE parser, mirroring the frontend's
    SseFrameAccumulator (src/api/sseParser.ts): every "data:" line
    contributes its value (minus exactly one leading delimiter space) to
    the reconstructed payload, joined back together with "\\n"."""
    assert wire.endswith("\n\n")
    block = wire[: -len("\n\n")]

    event = "message"
    data_lines: list[str] = []
    for line in block.split("\n"):
        if line.startswith("event:"):
            value = line[len("event:") :]
            event = value[1:] if value.startswith(" ") else value
        elif line.startswith("data:"):
            value = line[len("data:") :]
            data_lines.append(value[1:] if value.startswith(" ") else value)

    return event, "\n".join(data_lines)


def test_sse_single_line_round_trips_unchanged() -> None:
    """Regression: the pre-fix behavior for single-line data must be preserved."""
    wire = _sse("token", "hello")
    assert wire == "event: token\ndata: hello\n\n"
    assert _reference_parse(wire) == ("token", "hello")


def test_sse_multi_line_round_trips_exactly() -> None:
    """ORQ-19.1 / H4b fix: a chunk with an embedded newline (e.g. a code
    block or list spanning multiple lines) must be emitted as one "data:"
    line per line of the payload, per the SSE spec, and reconstruct exactly."""
    original = "line1\nline2\nline3"
    wire = _sse("token", original)
    assert wire == "event: token\ndata: line1\ndata: line2\ndata: line3\n\n"
    assert _reference_parse(wire) == ("token", original)


def test_sse_embedded_blank_line_round_trips_exactly() -> None:
    """An embedded blank line ("\\n\\n") must not be allowed to terminate
    the frame early — each split("\\n") element becomes its own "data:"
    line, including empty ones, so no bare "\\n\\n" can appear mid-frame."""
    original = "line1\n\nline3"
    wire = _sse("token", original)
    assert wire == "event: token\ndata: line1\ndata: \ndata: line3\n\n"
    # No blank line appears before the final frame terminator.
    assert "\n\n" not in wire[: -len("\n\n")]
    assert _reference_parse(wire) == ("token", original)


def test_sse_trailing_newline_round_trips_exactly() -> None:
    """split("\\n") (not splitlines()) preserves the empty trailing element
    produced by a payload that ends in "\\n" — splitlines() would silently
    drop it."""
    original = "line1\n"
    wire = _sse("token", original)
    assert wire == "event: token\ndata: line1\ndata: \n\n"
    assert _reference_parse(wire) == ("token", original)


def test_sse_empty_payload_round_trips_exactly() -> None:
    wire = _sse("token", "")
    assert wire == "event: token\ndata: \n\n"
    assert _reference_parse(wire) == ("token", "")


def test_sse_json_is_observably_unchanged_for_done() -> None:
    """_sse_json() (used only for `done`/`error`) must remain a no-op
    change from this fix: json.dumps(..., separators=(",", ":")) never
    produces a raw embedded newline, so it always yields exactly one
    "data:" line, identical to the pre-fix behavior."""
    payload = {"request_id": "r1", "conversation_id": "c1", "status": "success"}
    wire = _sse_json("done", payload)

    expected_data = json.dumps(payload, separators=(",", ":"))
    assert "\n" not in expected_data
    assert wire == f"event: done\ndata: {expected_data}\n\n"

    event, data = _reference_parse(wire)
    assert event == "done"
    assert json.loads(data) == payload


def test_sse_json_is_observably_unchanged_for_error() -> None:
    """Same guarantee as the `done` case, exercised directly for `error`
    (Execution Review F1) since it is the other real call site of
    _sse_json() and has its own payload shape."""
    payload = {"error_kind": "internal"}
    wire = _sse_json("error", payload)

    expected_data = json.dumps(payload, separators=(",", ":"))
    assert "\n" not in expected_data
    assert wire == f"event: error\ndata: {expected_data}\n\n"

    event, data = _reference_parse(wire)
    assert event == "error"
    assert json.loads(data) == payload
