"""ORQ-37 T23 — the gate-threshold measurement campaign (AC7/AC31).

Campaign instrumentation, not production code. Lives under `experiments/`
alongside `run_evaluation.py` for the same reason: it measures the shipped
system without being part of it.

**What this drives.** The real `/chat` route through the real ASGI app, with
the real memory and RAG dependencies, against the frozen ORQ-26 corpus in
tenant `orq37-t23`. Nothing is stubbed except the clock we read.

**Provider-call counts come from tracing spans** (operator decision,
2026-09-13), not from `rag_request_metrics` columns: the stage spans
(`rag.rewrite`, `rag.retrieve`, `rag.rerank`, `rag.evaluate`, `rag.generate`,
`memory.assemble`, `memory.rank`) already exist and are already asserted by
AC3's tests, while the `*_calls` columns have no producer and wiring one is
H7 Class 3, explicitly out of scope here.

**Cost surfaces are kept separate**, matching the frozen contract:
  * generation -- read from the persisted `estimated_cost_usd`, which is
    generation-only by design;
  * rerank -- counted here and priced at USD 1.00 / 1000 ranking queries
    (GCP Ranking API snapshot, 2026-09-13);
  * embeddings -- counted here and priced from `EMBEDDING_PRICE_SNAPSHOT`.
Nothing about `rag_request_metrics` changes.

**p95 is nearest-rank**, reusing `tuning.percentiles` rather than a second
implementation, and is computed over the three measured runs POOLED -- the
protocol §Diseño 1 states. The warm-up pass is run and discarded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.evaluation.tuning import percentiles  # noqa: E402

GOLDEN_SET = Path(__file__).with_name("golden_set.jsonl")
RERANK_USD_PER_1K_QUERIES = 1.00  # GCP Ranking API snapshot, 2026-09-13
TENANT = "orq37-t23"


@dataclass
class RequestSample:
    arm: str
    run: int
    query_id: str
    latency_ms: float
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    memory_outcome: str | None = None
    mode: str | None = None
    stage_spans: dict[str, int] = field(default_factory=dict)
    rerank_calls: int = 0
    embedding_calls: int = 0
    embedding_tokens: int = 0
    generation_calls: int = 0
    provider_fallback: bool = False
    rerank_fallback: bool = False
    error: str | None = None


class CountingTracer:
    """Records which stage spans were entered, per request.

    This is the provider-call-count instrument. It is a tracer double in the
    same seam production uses (`tracing.configure_for_testing`), so "tracing
    enabled" for Gate A means this object is installed and "disabled" means it
    is not -- the arm flag and the instrument are the same switch, which is
    why Gate A's comparison is meaningful rather than circular.
    """

    def __init__(self) -> None:
        self.spans: dict[str, int] = {}

    def reset(self) -> None:
        self.spans = {}

    def start_as_current_span(self, name):
        self.spans[name] = self.spans.get(name, 0) + 1
        tracer = self

        class _Span:
            def set_attribute(self, key, value):
                return None

        class _CM:
            def __enter__(self):
                return _Span()

            def __exit__(self, *exc):
                return False

        return _CM()


def load_golden_set() -> list[dict[str, Any]]:
    return [json.loads(line) for line in GOLDEN_SET.read_text().splitlines() if line.strip()]


def pool_p95(samples: list[float]) -> tuple[float, float]:
    """p50/p95, nearest-rank, over the POOLED measured runs (§Diseño 1)."""
    if not samples:
        return 0.0, 0.0
    return percentiles(samples)


def summarize(arm: str, samples: list[RequestSample]) -> dict[str, Any]:
    ok = [s for s in samples if s.error is None]
    latencies = [s.latency_ms for s in ok]
    p50, p95 = pool_p95(latencies)
    costs = [s.estimated_cost_usd for s in ok if s.estimated_cost_usd is not None]
    cost_p50, cost_p95 = pool_p95(costs) if costs else (0.0, 0.0)

    stage_totals: dict[str, int] = {}
    for s in ok:
        for name, n in s.stage_spans.items():
            stage_totals[name] = stage_totals.get(name, 0) + n

    return {
        "arm": arm,
        "requests_measured": len(ok),
        "errors": len(samples) - len(ok),
        "latency_ms_p50": round(p50, 1),
        "latency_ms_p95": round(p95, 1),
        "generation_cost_usd_total": round(sum(costs), 6),
        "generation_cost_usd_p95": cost_p95,
        "priced_requests": len(costs),
        "unpriced_requests": len(ok) - len(costs),
        "stage_spans": stage_totals,
        "rerank_calls": sum(s.rerank_calls for s in ok),
        "embedding_calls": sum(s.embedding_calls for s in ok),
        "embedding_tokens": sum(s.embedding_tokens for s in ok),
        "provider_fallback_events": sum(1 for s in ok if s.provider_fallback),
        "rerank_fallback_events": sum(1 for s in ok if s.rerank_fallback),
        "modes": sorted({s.mode for s in ok if s.mode}),
        "memory_outcomes": sorted({s.memory_outcome for s in ok if s.memory_outcome}),
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", required=True, help="Arm label, recorded in the evidence.")
    p.add_argument("--runs", type=int, default=3, help="Measured runs (§Diseño 1 requires 3).")
    p.add_argument("--warmup", action="store_true", help="Run one discarded warm-up pass first.")
    p.add_argument("--limit", type=int, default=None, help="Queries per run; default = all 60.")
    p.add_argument("--out", type=Path, required=True, help="Where to write raw per-request JSON.")
    return p.parse_args(argv)
