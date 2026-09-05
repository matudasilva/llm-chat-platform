"""ORQ-37 Gate A, T4 — AC5: dashboard references resolve against the schema.

D-4 ships no hosted backend, so nothing renders this dashboard during
implementation. That is exactly why the check has to be mechanical: a panel
naming a field nobody emits would otherwise surface as an empty graph long
after the ORQ closed.

Half of these tests assert the checker **fails** on a bad artifact. A checker
that only ever passes is indistinguishable from one that checks nothing -- the
same trap §Diseño 12 avoided by enumerating its forbidden phrases instead of
referring to a list nobody wrote.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from app.core.observability import schema
from app.scripts.check_dashboard_schema import (
    DEFAULT_DASHBOARD,
    SPAN_INTRINSIC_FIELDS,
    check,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def dashboard() -> dict:
    return json.loads(DEFAULT_DASHBOARD.read_text(encoding="utf-8"))


def _write(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- The shipped artifact --------------------------------------------------


def test_shipped_dashboard_resolves_completely():
    findings, counts = check(DEFAULT_DASHBOARD)
    assert findings == [], findings
    assert counts["panels"] > 0 and counts["references"] > 0


def test_the_script_exits_zero_and_prints_raw_evidence():
    result = subprocess.run(
        [sys.executable, "app/scripts/check_dashboard_schema.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT dashboard_schema=ok findings=0" in result.stdout
    assert "references checked" in result.stdout


def test_every_emitting_stage_span_is_covered_by_some_panel(dashboard):
    """A schema-valid dashboard that graphs nothing would still pass the
    reference check, so coverage is asserted separately."""
    covered = {name for panel in dashboard["panels"] for name in panel["spans"]}
    assert schema.RAG_SPAN_NAMES <= covered


def test_pending_panels_are_the_ones_whose_spans_do_not_exist_yet(dashboard):
    pending = {p["id"]: p for p in dashboard["panels"] if p["status"] == "pending"}
    assert set(pending) == {"request_overview", "memory_stages"}
    for panel in pending.values():
        assert panel["pending_reason"]


def test_no_panel_references_duration_as_an_attribute(dashboard):
    """`stage.duration_ms` was removed from the allow-list precisely so this
    cannot happen; the artifact must read duration from the span."""
    for panel in dashboard["panels"]:
        assert not any("duration" in key for key in panel["attributes"]), panel["id"]
    graphing_latency = [p for p in dashboard["panels"] if "duration" in p["span_fields"]]
    assert graphing_latency, "no panel graphs latency at all"


def test_no_collector_endpoint_is_committed():
    """tech-stack.md §Constraints: this is a public repository."""
    import re

    # A concrete collector target is a URL, a host:port, or an OTLP port.
    # Scoped to this ORQ's own surface: `.env.example` legitimately carries
    # unrelated URLs (CORS origins), which are not this criterion's business.
    target = re.compile(r"https?://\S+|\b\d{1,3}(?:\.\d{1,3}){3}:\d+\b|:431[78]\b")

    hits = target.findall(DEFAULT_DASHBOARD.read_text(encoding="utf-8"))
    assert hits == [], f"the dashboard artifact commits a collector target: {hits}"

    env_lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    otel_lines = [line for line in env_lines if line.startswith("OTEL_")]
    assert otel_lines, "the OTEL_* settings are not documented in .env.example"
    hits = [h for line in otel_lines for h in target.findall(line)]
    assert hits == [], f".env.example commits a collector target: {hits}"
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=" in otel_lines, "the endpoint must ship empty"


# --- The checker actually catches things -----------------------------------


def test_an_undeclared_attribute_is_reported(tmp_path, dashboard):
    dashboard["panels"][1]["attributes"] = ["rag.query_text"]
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("rag.query_text" in f and "allow-list" in f for f in findings)


def test_an_undeclared_span_is_reported(tmp_path, dashboard):
    dashboard["panels"][1]["spans"] = ["rag.summarize"]
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("rag.summarize" in f for f in findings)


def test_an_attribute_listed_as_a_span_field_is_reported(tmp_path, dashboard):
    dashboard["panels"][1]["span_fields"] = ["rag.candidate_count"]
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("is an attribute, not a span-intrinsic field" in f for f in findings)


def test_an_unknown_span_field_is_reported(tmp_path, dashboard):
    dashboard["panels"][1]["span_fields"] = ["stage.duration_ms"]
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("stage.duration_ms" in f for f in findings)


def test_a_pending_panel_without_a_reason_is_reported(tmp_path, dashboard):
    dashboard["panels"][0].pop("pending_reason")
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("pending_reason" in f for f in findings)


def test_duplicate_panel_ids_are_reported(tmp_path, dashboard):
    dashboard["panels"].append(dict(dashboard["panels"][1]))
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("duplicate panel id" in f for f in findings)


def test_a_panel_referencing_no_span_is_reported(tmp_path, dashboard):
    dashboard["panels"][1]["spans"] = []
    findings, _ = check(_write(tmp_path, dashboard))
    assert any("references no span" in f for f in findings)


def test_a_missing_or_malformed_artifact_is_reported(tmp_path):
    findings, _ = check(tmp_path / "absent.json")
    assert any("not found" in f for f in findings)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    findings, _ = check(broken)
    assert any("not valid JSON" in f for f in findings)


def test_the_script_exits_nonzero_on_a_bad_artifact(tmp_path, dashboard):
    dashboard["panels"][1]["attributes"] = ["rag.query_text"]
    path = _write(tmp_path, dashboard)
    result = subprocess.run(
        [sys.executable, "app/scripts/check_dashboard_schema.py", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "RESULT dashboard_schema=failed" in result.stdout


# --- Settings surface ------------------------------------------------------


def test_the_export_target_is_configuration_and_defaults_to_unset():
    from app.core.settings import Settings

    settings = Settings(_env_file=None)
    assert settings.otel_enabled is False
    assert settings.otel_exporter_otlp_endpoint is None


def test_the_endpoint_is_read_from_the_environment(monkeypatch):
    from app.core.settings import Settings

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.internal:1234/v1/traces")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.otel_enabled is True
    assert settings.otel_exporter_otlp_endpoint == "http://collector.internal:1234/v1/traces"


def test_enabling_without_an_endpoint_leaves_the_seam_inert():
    """Misconfiguration degrades to a no-op; it never breaks start-up."""
    from app.core.observability import tracing

    class _Config:
        otel_enabled = True
        otel_exporter_otlp_endpoint = None

    try:
        assert tracing.init_tracing(config=_Config()) is False
        assert tracing.is_enabled() is False
    finally:
        tracing.configure_for_testing(None)


def test_span_intrinsic_fields_and_attributes_do_not_overlap():
    assert SPAN_INTRINSIC_FIELDS & schema.ALLOWED_ATTRIBUTE_KEYS == set()
