"""ORQ-37 T6 — the pure logic of a tuning sweep, separated so it is testable.

Lives under `experiments/` and not `app/` deliberately: it imports
`experiments.evaluation.metrics`, and AC23 forbids any module under `app/` from
importing `experiments/`. A tuning harness placed in `app/scripts/` would have
been the natural-looking home and would have broken that boundary.

Nothing here touches a database, a network or a clock. The measurement loop
that does lives in `run_tuning_sweep.py`.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# §Diseño 1, "No quality regression": every retrieval metric the ORQ-26 harness
# already emits, compared per metric, **tolerance 0** -- any decrease fails. No
# new metric is introduced here; that would change what the golden set means.
REGRESSION_TOLERANCE = 0.0


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """One configuration to measure. `top_n` is carried but NOT measured here.

    The ORQ-26 harness measures `PgVectorStore.hybrid_search` alone -- zero LLM
    and zero reranker calls (its README and registration both say so). `top_n`
    governs the reranker, so the golden set is structurally unable to observe
    it. Carrying the value keeps the recommendation honest about which
    parameter each number actually supports.
    """

    top_k_candidates: int
    top_n: int

    @property
    def label(self) -> str:
        return f"top_k={self.top_k_candidates},top_n={self.top_n}"


@dataclass(frozen=True, slots=True)
class SweepResult:
    point: SweepPoint
    metrics: Mapping[str, float]
    latency_ms_p50: float
    latency_ms_p95: float
    embedding_calls: int
    estimated_cost_usd: float
    measured: bool = True
    note: str = ""


@dataclass(frozen=True, slots=True)
class RegressionFinding:
    metric: str
    baseline: float
    candidate: float

    @property
    def delta(self) -> float:
        return self.candidate - self.baseline

    def __str__(self) -> str:
        return f"{self.metric}: {self.baseline:.4f} -> {self.candidate:.4f} ({self.delta:+.4f})"


@dataclass(frozen=True, slots=True)
class Comparison:
    baseline: SweepResult
    candidate: SweepResult
    regressions: tuple[RegressionFinding, ...] = field(default=())
    improvements: tuple[RegressionFinding, ...] = field(default=())

    @property
    def no_regression(self) -> bool:
        return not self.regressions

    @property
    def recommendation(self) -> str:
        """A recommendation, never an applied change (D-3).

        A candidate that regresses nothing is not automatically better: it may
        cost more for no gain. The three verdicts keep that distinction visible
        instead of collapsing it into pass/fail.
        """
        if self.regressions:
            return "reject"
        if self.improvements:
            return "propose-to-operator"
        return "no-change-justified"


def compare(baseline: SweepResult, candidate: SweepResult) -> Comparison:
    """Per-metric comparison at tolerance 0, over the metrics they share.

    Refuses silently-partial comparisons: a metric present in one and missing
    from the other means the two runs are not comparable, and pretending
    otherwise is how a regression hides.
    """
    if set(baseline.metrics) != set(candidate.metrics):
        raise ValueError(
            "baseline and candidate expose different metrics: "
            f"{sorted(set(baseline.metrics) ^ set(candidate.metrics))}"
        )

    regressions: list[RegressionFinding] = []
    improvements: list[RegressionFinding] = []
    for metric in sorted(baseline.metrics):
        before, after = baseline.metrics[metric], candidate.metrics[metric]
        if after < before - REGRESSION_TOLERANCE:
            regressions.append(RegressionFinding(metric, before, after))
        elif after > before:
            improvements.append(RegressionFinding(metric, before, after))

    return Comparison(
        baseline=baseline,
        candidate=candidate,
        regressions=tuple(regressions),
        improvements=tuple(improvements),
    )


def default_grid(*, shipped_top_k: int, shipped_top_n: int) -> tuple[SweepPoint, ...]:
    """The shipped configuration first, then neighbours.

    The shipped point leads so the baseline is measured under the same
    conditions as every candidate, in the same run -- comparing against a figure
    captured on another day would fold corpus and provider drift into the
    'tuning' delta.
    """
    baseline = SweepPoint(shipped_top_k, shipped_top_n)
    neighbours = [
        SweepPoint(top_k, shipped_top_n)
        for top_k in (10, 15, 30, 40)
        if top_k != shipped_top_k
    ]
    return (baseline, *neighbours)


def render_table(results: Sequence[SweepResult]) -> str:
    """A markdown table for `implementation.md`. AC7 wants raw evidence."""
    if not results:
        return "_no results_"
    metric_names = sorted(results[0].metrics)
    header = (
        ["config"]
        + metric_names
        + ["p50 ms", "p95 ms", "embed calls", "est. cost USD", "measured"]
    )
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for result in results:
        row = (
            [result.point.label]
            + [f"{result.metrics.get(name, float('nan')):.4f}" for name in metric_names]
            + [
                f"{result.latency_ms_p50:.1f}",
                f"{result.latency_ms_p95:.1f}",
                str(result.embedding_calls),
                f"{result.estimated_cost_usd:.6f}",
                "yes" if result.measured else "NO",
            ]
        )
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def percentiles(samples: Sequence[float]) -> tuple[float, float]:
    """p50 and p95, nearest-rank. Deterministic, and defined for one sample."""
    if not samples:
        return (0.0, 0.0)
    ordered = sorted(samples)

    def _at(fraction: float) -> float:
        # Nearest-rank: ceil(p * N) - 1. `round` is wrong here -- it applies
        # banker's rounding, so p95 over 100 samples landed one rank high.
        index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
        return ordered[index]

    return (_at(0.50), _at(0.95))


def summarize(payload: Mapping[str, Any]) -> dict[str, float]:
    """Keep only the aggregate retrieval metrics, in a stable order."""
    return {key: float(value) for key, value in sorted(payload.items())}
