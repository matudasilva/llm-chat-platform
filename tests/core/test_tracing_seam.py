"""ORQ-37 Gate A — the tracing seam (AC1, AC2 at the seam, AC4).

AC2's end-to-end half (identical `/chat` and `/retrieval` responses under a
faulty tracer) lands with T2, which is what puts spans on those paths. What is
asserted here is the property T2 will rely on: the seam itself neither raises
nor blocks, whatever the tracer does.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import threading
import time

import pytest

from app.core.observability import schema, tracing


@pytest.fixture(autouse=True)
def _reset_seam():
    tracing.configure_for_testing(None)
    tracing.reset_rejected_attribute_keys()
    yield
    tracing.configure_for_testing(None)
    tracing.reset_rejected_attribute_keys()


# --- Doubles --------------------------------------------------------------


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: dict[str, _RecordingSpan] = {}

    def start_as_current_span(self, name):
        span = _RecordingSpan()
        self.spans[name] = span
        tracer = self

        class _CM:
            def __enter__(self):
                return span

            def __exit__(self, *exc):
                tracer.exited = True
                return False

        return _CM()


class _RaisingTracer:
    """Raises on every span, at every point a tracer can raise."""

    def start_as_current_span(self, name):
        raise RuntimeError("tracer is broken")


class _RaisingOnAttributeTracer:
    def start_as_current_span(self, name):
        class _Span:
            def set_attribute(self, key, value):
                raise RuntimeError("attribute sink is broken")

        class _CM:
            def __enter__(self):
                return _Span()

            def __exit__(self, *exc):
                raise RuntimeError("exit is broken")

        return _CM()


# --- AC1: single importer -------------------------------------------------


def test_tracing_is_the_only_module_importing_opentelemetry():
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    # Restricted to Python sources: AC1 is about *modules*, and `app/` also
    # holds the requirements files, where the dependency must appear.
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "opentelemetry", str(root)],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    offenders = sorted(
        {
            line.split(":", 1)[0]
            for line in hits
            if not line.split(":", 1)[0].endswith("observability/tracing.py")
        }
    )
    assert offenders == [], f"opentelemetry imported outside the seam: {offenders}"


def test_lifespan_bootstrap_lives_in_the_seam_not_in_main():
    main = (pathlib.Path(__file__).resolve().parents[2] / "app" / "main.py").read_text()
    assert "opentelemetry" not in main
    assert "init_tracing" in main and "shutdown_tracing" in main


# --- Default state --------------------------------------------------------


def test_disabled_by_default_is_a_no_op():
    assert tracing.is_enabled() is False
    with tracing.span("rag.retrieve", **{"rag.candidate_count": 3}) as current:
        assert current is None


def test_init_tracing_returns_false_when_disabled():
    class _Config:
        otel_enabled = False

    assert tracing.init_tracing(config=_Config()) is False
    assert tracing.is_enabled() is False


def test_init_tracing_returns_false_without_an_endpoint():
    class _Config:
        otel_enabled = True
        otel_exporter_otlp_endpoint = None

    assert tracing.init_tracing(config=_Config()) is False


# --- AC2 (seam level): a faulty tracer changes nothing ---------------------


def test_raising_tracer_does_not_propagate():
    tracing.configure_for_testing(_RaisingTracer())
    with tracing.span("rag.generate") as current:
        assert current is None  # degrades to the no-op state


def test_raising_attribute_sink_and_exit_do_not_propagate():
    tracing.configure_for_testing(_RaisingOnAttributeTracer())
    with tracing.span("rag.rerank", **{"rag.ranked_count": 5}):
        pass  # a raising set_attribute and a raising __exit__ are swallowed


def test_body_exceptions_still_propagate():
    """The seam swallows its own failures, never the caller's."""
    tracing.configure_for_testing(_RecordingTracer())
    with pytest.raises(ValueError, match="business failure"):
        with tracing.span("rag.generate"):
            raise ValueError("business failure")


def test_body_exception_is_reported_to_the_span_manager():
    tracer = _RecordingTracer()
    tracing.configure_for_testing(tracer)
    with pytest.raises(ValueError):
        with tracing.span("rag.generate"):
            raise ValueError("boom")
    assert getattr(tracer, "exited", False) is True


def test_bounded_call_abandons_a_hung_callable():
    """A hung exporter costs a bounded wait, not an open-ended block."""
    started = threading.Event()

    def _hang():
        started.set()
        time.sleep(30)

    began = time.monotonic()
    completed = tracing._call_bounded(_hang, 0.05, "test")
    elapsed = time.monotonic() - began

    assert started.wait(1.0)
    assert completed is False
    assert elapsed < 5.0, f"bounded call blocked for {elapsed:.2f}s"


def test_shutdown_is_bounded_and_never_raises():
    class _HungProvider:
        def force_flush(self):
            time.sleep(30)

        def shutdown(self):
            time.sleep(30)

    class _Config:
        otel_flush_timeout_s = 0.05
        otel_shutdown_timeout_s = 0.05

    tracing.configure_for_testing(object(), _HungProvider())
    began = time.monotonic()
    tracing.shutdown_tracing(config=_Config())
    assert time.monotonic() - began < 5.0
    assert tracing.is_enabled() is False


# --- AC4: the allow-list is enforced --------------------------------------


def test_only_declared_attribute_keys_are_emitted():
    tracer = _RecordingTracer()
    tracing.configure_for_testing(tracer)
    with tracing.span(
        "rag.retrieve",
        **{
            "rag.candidate_count": 7,
            "rag.query_text": "the user's actual question",
            "chunk.text": "corpus content",
        },
    ):
        pass

    emitted = tracer.spans["rag.retrieve"].attributes
    assert emitted == {"rag.candidate_count": 7}
    assert set(tracing.rejected_attribute_keys()) == {"rag.query_text", "chunk.text"}


def test_set_attribute_helper_honours_the_allow_list():
    tracer = _RecordingTracer()
    tracing.configure_for_testing(tracer)
    with tracing.span("memory.rank") as current:
        tracing.set_attribute(current, "memory.selected_count", 5)
        tracing.set_attribute(current, "memory.selected_text", "prior user turn")

    assert tracer.spans["memory.rank"].attributes == {"memory.selected_count": 5}
    assert "memory.selected_text" in tracing.rejected_attribute_keys()


def test_none_values_are_dropped_without_being_reported_as_violations():
    tracer = _RecordingTracer()
    tracing.configure_for_testing(tracer)
    with tracing.span("rag.rerank", **{"rag.ranked_count": None}):
        pass
    assert tracer.spans["rag.rerank"].attributes == {}
    assert tracing.rejected_attribute_keys() == ()


def test_rejected_key_recording_is_bounded():
    tracing.configure_for_testing(_RecordingTracer())
    with tracing.span("rag.retrieve", **{f"undeclared.{i}": i for i in range(400)}):
        pass
    assert len(tracing.rejected_attribute_keys()) <= tracing._MAX_REJECTED


# --- The schema artifact itself -------------------------------------------


def test_schema_declares_the_seven_stage_spans_plus_the_request_span():
    assert schema.RAG_SPAN_NAMES == {
        "rag.rewrite",
        "rag.retrieve",
        "rag.rerank",
        "rag.evaluate",
        "rag.generate",
    }
    assert schema.MEMORY_SPAN_NAMES == {"memory.assemble", "memory.rank"}
    assert schema.REQUEST_SPAN in schema.SPAN_NAMES
    assert len(schema.SPAN_NAMES) == 8


def test_identity_keys_are_distinct_and_no_bare_request_id_exists():
    """§Diseño 3: identity is server-generated; the inbound header is only
    correlation metadata. A bare `request_id` key would conflate them."""
    assert "request.instance_id" in schema.ALLOWED_ATTRIBUTE_KEYS
    assert "request.correlation_id" in schema.ALLOWED_ATTRIBUTE_KEYS
    assert "request_id" not in schema.ALLOWED_ATTRIBUTE_KEYS


def test_no_declared_key_names_a_content_carrying_field():
    """AC4's rule as a property of the schema, not only of one emission."""
    forbidden = re.compile(
        r"(^|\.)(text|content|query|prompt|message|body|answer|chunk|snippet)$"
    )
    offenders = [k for k in schema.ALLOWED_ATTRIBUTE_KEYS if forbidden.search(k)]
    assert offenders == [], f"content-carrying keys declared: {offenders}"
