"""ORQ-37 Gate A, T6 — AC30 in full, and AC7's evidence machinery.

AC30 is closed here: the two fields are exposed at the values already in force,
the factory passes them, and no pre-existing default moved.

AC7 is **not** closed here, and these tests do not pretend otherwise. Its
evidence is a measured before/after against the ORQ-26 golden set, and that
harness needs a seeded pgvector corpus plus one embedding call per query --
credentials and spend, neither of which a test may assume. What is tested is
the machinery that will produce that evidence: the sweep grid, the tolerance-0
comparison, and the rendering.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import subprocess

import pytest

from app.core.domain.retrieval_factory import build_retrieval_pipeline
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.settings import Settings
from experiments.evaluation.tuning import (
    REGRESSION_TOLERANCE,
    SweepPoint,
    SweepResult,
    compare,
    default_grid,
    percentiles,
    render_table,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "app" / "core" / "settings.py"


# --- AC30: exposed at current values, nothing else moved -------------------


def test_the_two_exposed_fields_match_the_constructor_defaults():
    """§Diseño 5: exposing them must change no behaviour, so the settings value
    and the value already in force have to be the same number."""
    parameters = inspect.signature(RetrievalPipeline.__init__).parameters
    settings = Settings(_env_file=None)

    assert settings.retrieval_pipeline_top_k_candidates == parameters["top_k_candidates"].default == 20
    assert settings.retrieval_pipeline_top_n == parameters["top_n"].default == 5


def test_the_factory_actually_passes_them():
    """Before this task the fields existed on the pipeline but nothing supplied
    them, so no deployment could tune them. Exposure without wiring would have
    reproduced that."""
    source = inspect.getsource(build_retrieval_pipeline)
    assert "top_k_candidates=cfg.retrieval_pipeline_top_k_candidates" in source
    assert "top_n=cfg.retrieval_pipeline_top_n" in source


def test_the_pipeline_receives_the_configured_values(monkeypatch):
    captured: dict[str, object] = {}
    real_init = RetrievalPipeline.__init__

    def _spy(self, **kwargs):
        captured.update(kwargs)
        real_init(self, **kwargs)

    monkeypatch.setattr(RetrievalPipeline, "__init__", _spy)
    monkeypatch.setattr(
        "app.core.domain.retrieval_factory.build_embedding_provider", lambda cfg: object()
    )
    monkeypatch.setattr("app.core.domain.retrieval_factory.build_provider", lambda cfg: object())
    monkeypatch.setattr("app.core.domain.retrieval_factory.build_reranker", lambda cfg: object())

    settings = Settings(_env_file=None)
    object.__setattr__(settings, "retrieval_pipeline_top_k_candidates", 33)
    object.__setattr__(settings, "retrieval_pipeline_top_n", 7)
    build_retrieval_pipeline(db=object(), cfg=settings)

    assert captured["top_k_candidates"] == 33
    assert captured["top_n"] == 7


def test_no_pre_existing_default_changed():
    """AC30's real claim. Parses the previous and current settings.py and
    compares every field default, so a silent edit anywhere in the file fails
    here and not in production."""
    # Baseline is the branch point, NOT HEAD. An earlier version compared
    # against HEAD, which is self-invalidating: once this task's own commit
    # landed, HEAD already contained the new fields and the assertion silently
    # changed meaning. AC30's claim is "no default changed *by this ORQ*", so
    # the reference has to be where the ORQ started.
    base = subprocess.run(
        ["git", "merge-base", "main", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    previous_source = subprocess.run(
        ["git", "show", f"{base}:app/core/settings.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    def _defaults(source: str) -> dict[str, str]:
        tree = ast.parse(source)
        found: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    found[node.target.id] = ast.dump(node.value)
        return found

    before = _defaults(previous_source)
    after = _defaults(SETTINGS_PATH.read_text(encoding="utf-8"))

    changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
    assert changed == {}, f"pre-existing defaults changed: {sorted(changed)}"

    removed = sorted(set(before) - set(after))
    assert removed == [], f"settings fields disappeared: {removed}"

    # Every field this ORQ is authorized to add: T1's tracing seam, T6's two
    # exposed retrieval parameters and T7's operational credential. Anything
    # else appearing here is scope creep in settings.py, which is what AC30 is
    # really guarding. The list is extended per task, deliberately: an addition
    # has to be argued for once, here, rather than slipping in unremarked.
    authorized_additions = {
        "otel_enabled",
        "otel_service_name",
        "otel_exporter_otlp_endpoint",
        "otel_max_queue_size",
        "otel_max_export_batch_size",
        "otel_schedule_delay_ms",
        "otel_export_timeout_ms",
        "otel_init_timeout_s",
        "otel_flush_timeout_s",
        "otel_shutdown_timeout_s",
        "retrieval_pipeline_top_k_candidates",
        "retrieval_pipeline_top_n",
        # T7 / §Diseño 7: the least-privilege operational credential. Inert by
        # default (None), so it changes no shipped behaviour.
        "database_url_ops",
        # T9 / §Diseño 7: the memory rollout flag and its degradation bound.
        # Both inert by default (off, and a bound that only applies when on).
        "conversation_history_enabled",
        "conversation_history_timeout_s",
        # T12 / AC36: bounds the SQL history read. Inert until a conversation
        # exceeds it (default 2 000, far above the assembler's own window).
        "conversation_history_max_rows",
        # T13 / AC14: the hard added-context cap. 12 000 matches the ceiling
        # RAG alone already had, so this is a new NAME on an existing value,
        # not a new limit in practice.
        "chat_prompt_max_added_context_chars",
        # T14 / §Diseño 6: per-request metrics. Inert by default (flag off);
        # the retention window and write timeout are configuration only until
        # the flag is on, which Gate B2's production-readiness condition
        # separately gates.
        "rag_request_metrics_enabled",
        "rag_request_metrics_retention_days",
        "rag_request_metrics_timeout_s",
    }
    added = set(after) - set(before)
    assert added <= authorized_additions, (
        f"unauthorized new settings fields: {sorted(added - authorized_additions)}"
    )
    assert {"retrieval_pipeline_top_k_candidates", "retrieval_pipeline_top_n"} <= added


# --- AC23 boundary: the harness must not live under app/ -------------------


def test_the_tuning_harness_does_not_sit_under_app():
    """It imports experiments.evaluation.metrics, and AC23 forbids any module
    under app/ from importing experiments/. app/scripts/ was the natural-looking
    home and would have broken that boundary."""
    assert (REPO_ROOT / "experiments" / "evaluation" / "tuning.py").exists()
    assert not (REPO_ROOT / "app" / "scripts" / "tuning.py").exists()

    hits = subprocess.run(
        ["grep", "-rn", "-e", "^[[:space:]]*import experiments",
         "-e", "^[[:space:]]*from experiments", str(REPO_ROOT / "app")],
        capture_output=True,
        text=True,
    ).stdout
    assert hits == "", f"app/ imports experiments/: {hits}"


# --- AC7 machinery: the comparison rule ------------------------------------


def _result(point: SweepPoint, **metrics: float) -> SweepResult:
    return SweepResult(
        point=point,
        metrics=metrics,
        latency_ms_p50=10.0,
        latency_ms_p95=20.0,
        embedding_calls=60,
        estimated_cost_usd=0.001,
    )


def test_tolerance_is_zero_so_any_decrease_fails():
    """§Diseño 1 defines 'no quality regression' as tolerance 0. A tolerance
    that admits 'small' decreases would let tuning trade quality quietly."""
    assert REGRESSION_TOLERANCE == 0.0

    baseline = _result(SweepPoint(20, 5), **{"recall@10": 0.80})
    candidate = _result(SweepPoint(30, 5), **{"recall@10": 0.7999})

    comparison = compare(baseline, candidate)
    assert not comparison.no_regression
    assert comparison.recommendation == "reject"


def test_an_improvement_is_a_proposal_and_never_an_applied_change():
    """D-3: this ORQ may not change any shipped default."""
    baseline = _result(SweepPoint(20, 5), **{"recall@10": 0.80})
    candidate = _result(SweepPoint(30, 5), **{"recall@10": 0.85})

    comparison = compare(baseline, candidate)
    assert comparison.no_regression
    assert comparison.recommendation == "propose-to-operator"


def test_no_movement_is_reported_as_no_change_justified():
    baseline = _result(SweepPoint(20, 5), **{"recall@10": 0.80})
    candidate = _result(SweepPoint(30, 5), **{"recall@10": 0.80})
    assert compare(baseline, candidate).recommendation == "no-change-justified"


def test_a_mixed_result_is_a_rejection_not_an_average():
    """One metric up and another down is a regression. Averaging them away is
    exactly how a per-metric rule gets softened into a pooled one."""
    baseline = _result(SweepPoint(20, 5), **{"recall@10": 0.80, "MAP@10": 0.50})
    candidate = _result(SweepPoint(30, 5), **{"recall@10": 0.90, "MAP@10": 0.49})

    comparison = compare(baseline, candidate)
    assert comparison.recommendation == "reject"
    assert [f.metric for f in comparison.regressions] == ["MAP@10"]
    assert [f.metric for f in comparison.improvements] == ["recall@10"]


def test_comparing_different_metric_sets_is_refused():
    """A metric present in one run and missing from the other means the runs
    are not comparable; comparing the intersection is how a regression hides."""
    baseline = _result(SweepPoint(20, 5), **{"recall@10": 0.8, "MAP@10": 0.5})
    candidate = _result(SweepPoint(30, 5), **{"recall@10": 0.8})

    with pytest.raises(ValueError, match="different metrics"):
        compare(baseline, candidate)


def test_the_grid_measures_the_shipped_point_in_the_same_run():
    """Comparing against a figure captured on another day would fold corpus and
    provider drift into the 'tuning' delta."""
    grid = default_grid(shipped_top_k=20, shipped_top_n=5)
    assert grid[0] == SweepPoint(20, 5)
    assert len({p.top_k_candidates for p in grid}) == len(grid)
    assert all(p.top_n == 5 for p in grid), "the grid must not vary top_n; see below"


def test_the_grid_does_not_vary_top_n_because_the_golden_set_cannot_see_it():
    """The ORQ-26 harness measures hybrid_search alone -- zero reranker calls --
    so no golden-set number can support a top_n recommendation. Sweeping it
    would produce numbers that look like evidence and are not."""
    grid = default_grid(shipped_top_k=20, shipped_top_n=5)
    assert len({p.top_n for p in grid}) == 1

    readme = (REPO_ROOT / "experiments" / "evaluation" / "README.md").read_text(encoding="utf-8")
    assert "zero LLM and zero reranker calls" in readme


def test_percentiles_are_deterministic_and_defined_for_one_sample():
    assert percentiles([]) == (0.0, 0.0)
    assert percentiles([7.0]) == (7.0, 7.0)
    p50, p95 = percentiles([float(n) for n in range(1, 101)])
    assert p50 == 50.0 and p95 == 95.0


def test_the_table_marks_unmeasured_rows_loudly():
    """A row that was not measured must not read like one that was."""
    measured = _result(SweepPoint(20, 5), **{"recall@10": 0.8})
    unmeasured = SweepResult(
        point=SweepPoint(30, 5),
        metrics={"recall@10": float("nan")},
        latency_ms_p50=0.0,
        latency_ms_p95=0.0,
        embedding_calls=0,
        estimated_cost_usd=0.0,
        measured=False,
        note="requires a live corpus",
    )
    table = render_table([measured, unmeasured])
    assert "| yes |" in table and "| NO |" in table
