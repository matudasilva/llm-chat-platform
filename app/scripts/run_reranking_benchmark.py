from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import hashlib
import itertools
import json
import logging
import math
import os
from pathlib import Path
import platform
import random
import statistics
import time
from typing import Any

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.gcp_reranker import GcpReranker
from app.core.providers.qwen_local_reranker import QwenLocalReranker
from app.core.settings import settings

logger = logging.getLogger(__name__)

_METRICS = ("ndcg_at_10", "mrr_at_10", "hit_rate_at_5")
_SAFE_TELEMETRY_FIELDS = {"backend", "model", "candidate_count", "latency_ms", "outcome", "error_kind"}
_AWS_THROTTLE_FINDING = (
    "Preparation finding: 8 rapid Bedrock Rerank calls throttled all tested regions; "
    "4-second spacing with retries still failed; approximately 15-second spacing succeeded."
)


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_dataset_sha256(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip().split()[0]
    if len(value) != 64:
        raise ValueError("dataset SHA-256 file is invalid")
    return value


def verify_dataset_hash(dataset_path: Path, sha_path: Path) -> str:
    actual = dataset_sha256(dataset_path)
    expected = expected_dataset_sha256(sha_path)
    if actual != expected:
        raise ValueError(f"dataset SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def load_dataset(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != 60 or any(len(row.get("candidates", [])) != 30 for row in rows):
        raise ValueError("dataset must contain exactly 60 rows with 30 candidates each")
    return rows


def emit_reranker_event(
    sink: Callable[[str, dict[str, Any]], None],
    event: str,
    **payload: Any,
) -> None:
    safe_payload = {key: value for key, value in payload.items() if key in _SAFE_TELEMETRY_FIELDS}
    try:
        sink(event, safe_payload)
    except Exception:
        return


def _logging_sink(event: str, payload: dict[str, Any]) -> None:
    logger.info(event, extra={"event": event, **payload})


class JsonlResultStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def keys(self) -> set[tuple[str, str, int]]:
        return {
            (str(row["phase"]), str(row["query_id"]), int(row["repetition"]))
            for row in self.load()
        }

    def append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def reset(self) -> None:
        self.path.write_text("", encoding="utf-8")


class CallBudget:
    def __init__(self, calls: int) -> None:
        self.remaining = calls

    def consume(self) -> None:
        if self.remaining <= 0:
            raise TerminalRerankerError("GCP call budget exhausted", backend="gcp")
        self.remaining -= 1


class Pacer:
    def __init__(self, spacing_s: float) -> None:
        self._spacing_s = spacing_s
        self._last_call: float | None = None

    async def wait(self) -> None:
        if self._last_call is not None:
            remaining = self._spacing_s - (time.monotonic() - self._last_call)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_call = time.monotonic()


def _documents(row: dict[str, Any]) -> tuple[str, ...]:
    documents = tuple(candidate["text"] for candidate in row["candidates"])
    if any(len(document.encode("utf-8")) > 1024 for document in documents):
        raise ValueError("candidate exceeds the 1024-token conservative byte ceiling")
    return documents


async def _invoke_with_retry(
    *,
    adapter: RerankerPort,
    request: RerankRequest,
    backend: str,
    model: str,
    pacer: Pacer | None,
    budget: CallBudget | None,
    telemetry: Callable[[str, dict[str, Any]], None],
    max_attempts: int = 5,
) -> tuple[list[RankedDocument], float, str | None]:
    for attempt in range(1, max_attempts + 1):
        if pacer is not None:
            await pacer.wait()
        if budget is not None:
            budget.consume()
        start = time.monotonic()
        emit_reranker_event(
            telemetry,
            "reranker.request",
            backend=backend,
            model=model,
            candidate_count=len(request.documents),
            outcome="started",
        )
        try:
            results = list(await adapter.rerank(request))
            latency_ms = (time.monotonic() - start) * 1000
            emit_reranker_event(
                telemetry,
                "reranker.response",
                backend=backend,
                model=model,
                candidate_count=len(request.documents),
                latency_ms=round(latency_ms, 3),
                outcome="ok",
            )
            return results, latency_ms, None
        except TerminalRerankerError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            emit_reranker_event(
                telemetry,
                "reranker.error",
                backend=backend,
                model=model,
                candidate_count=len(request.documents),
                latency_ms=round(latency_ms, 3),
                outcome="terminal",
                error_kind=exc.error_code or type(exc).__name__,
            )
            return [], latency_ms, exc.error_code or type(exc).__name__
        except TransientRerankerError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            if attempt == max_attempts:
                return [], latency_ms, exc.error_code or type(exc).__name__
            base = 15.0 if backend == "aws" else 1.0
            await asyncio.sleep(min(120.0, base * (2 ** (attempt - 1))))
    raise AssertionError("retry loop exhausted unexpectedly")


async def run_arm(
    *,
    arm: str,
    model: str,
    adapter: RerankerPort,
    dataset: Sequence[dict[str, Any]],
    store: JsonlResultStore,
    repetitions: int,
    warmups: int,
    phase: str,
    pacer: Pacer | None = None,
    budget: CallBudget | None = None,
    telemetry: Callable[[str, dict[str, Any]], None] = _logging_sink,
) -> None:
    existing = store.keys()
    warmup_rows = dataset[:warmups]
    for index, row in enumerate(warmup_rows):
        key = (f"{phase}_warmup", row["query_id"], index)
        if key in existing:
            continue
        results, latency_ms, error = await _invoke_with_retry(
            adapter=adapter,
            request=RerankRequest(query=row["query"], documents=_documents(row), top_n=30),
            backend=arm,
            model=model,
            pacer=pacer,
            budget=budget,
            telemetry=telemetry,
        )
        store.append(_raw_row(arm, model, row, index, f"{phase}_warmup", results, latency_ms, error))

    for row in dataset:
        for repetition in range(repetitions):
            key = (phase, row["query_id"], repetition)
            if key in existing:
                continue
            results, latency_ms, error = await _invoke_with_retry(
                adapter=adapter,
                request=RerankRequest(query=row["query"], documents=_documents(row), top_n=30),
                backend=arm,
                model=model,
                pacer=pacer,
                budget=budget,
                telemetry=telemetry,
            )
            store.append(_raw_row(arm, model, row, repetition, phase, results, latency_ms, error))


def _raw_row(
    arm: str,
    model: str,
    dataset_row: dict[str, Any],
    repetition: int,
    phase: str,
    results: Sequence[RankedDocument],
    latency_ms: float,
    error: str | None,
) -> dict[str, Any]:
    return {
        "arm": arm,
        "model": model,
        "phase": phase,
        "query_id": dataset_row["query_id"],
        "language": dataset_row["language"],
        "repetition": repetition,
        "ranking": [result.index for result in results],
        "scores": [result.relevance_score for result in results],
        "latency_ms": round(latency_ms, 6),
        "error": error,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def baseline_records(dataset: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "arm": "baseline",
            "model": "rrf_order",
            "phase": "benchmark",
            "query_id": row["query_id"],
            "language": row["language"],
            "repetition": 0,
            "ranking": list(range(30)),
            "scores": [None] * 30,
            "latency_ms": 0.0,
            "error": None,
        }
        for row in dataset
    ]


def _quality(ranking: Sequence[int], row: dict[str, Any]) -> dict[str, float]:
    grades = [int(candidate["relevance"]) for candidate in row["candidates"]]
    ranked_grades = [grades[index] for index in ranking if 0 <= index < len(grades)]
    dcg = sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(ranked_grades[:10]))
    ideal = sorted(grades, reverse=True)
    idcg = sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(ideal[:10]))
    relevant_ranks = [rank for rank, grade in enumerate(ranked_grades[:10], start=1) if grade >= 1]
    return {
        "ndcg_at_10": dcg / idcg if idcg else 0.0,
        "mrr_at_10": 1.0 / relevant_ranks[0] if relevant_ranks else 0.0,
        "hit_rate_at_5": float(any(grade >= 1 for grade in ranked_grades[:5])),
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def arm_metrics(
    dataset: Sequence[dict[str, Any]],
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rows_by_id = {row["query_id"]: row for row in dataset}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    benchmark_records = [record for record in records if record.get("phase") == "benchmark"]
    for record in benchmark_records:
        grouped[record["query_id"]].append(record)

    per_query: dict[str, dict[str, float]] = {}
    for query_id, row in rows_by_id.items():
        query_metrics = [
            _quality(record.get("ranking", []), row)
            for record in grouped.get(query_id, [])
        ]
        if not query_metrics:
            query_metrics = [{metric: 0.0 for metric in _METRICS}]
        per_query[query_id] = {
            metric: _mean([values[metric] for values in query_metrics])
            for metric in _METRICS
        }

    by_language: dict[str, dict[str, float]] = {}
    for language in ("en", "es"):
        ids = [row["query_id"] for row in dataset if row["language"] == language]
        by_language[language] = {
            metric: _mean([per_query[query_id][metric] for query_id in ids])
            for metric in _METRICS
        }
    latencies = [float(record["latency_ms"]) for record in benchmark_records if not record.get("error")]
    errors = sum(bool(record.get("error")) for record in benchmark_records)
    return {
        "aggregate": {
            metric: _mean([values[metric] for values in per_query.values()])
            for metric in _METRICS
        },
        "by_language": by_language,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "samples": len(latencies),
        },
        "error_rate": errors / len(benchmark_records) if benchmark_records else 0.0,
        "per_query": per_query,
    }


def bootstrap_ci(
    left: Sequence[float],
    right: Sequence[float],
    *,
    samples: int = 10_000,
    seed: int = 22,
) -> tuple[float, float, float]:
    if len(left) != len(right) or not left:
        raise ValueError("paired bootstrap inputs must be non-empty and equally sized")
    differences = [a - b for a, b in zip(left, right)]
    rng = random.Random(seed)
    estimates = [
        _mean([differences[rng.randrange(len(differences))] for _ in differences])
        for _ in range(samples)
    ]
    return _mean(differences), float(_percentile(estimates, 0.025)), float(_percentile(estimates, 0.975))


def comparison_table(metrics_by_arm: dict[str, dict[str, Any]], query_order: Sequence[str]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for left, right in itertools.combinations(sorted(metrics_by_arm), 2):
        for metric_index, metric in enumerate(_METRICS):
            difference, low, high = bootstrap_ci(
                [metrics_by_arm[left]["per_query"][query_id][metric] for query_id in query_order],
                [metrics_by_arm[right]["per_query"][query_id][metric] for query_id in query_order],
                seed=22 + metric_index,
            )
            outcome = "tie" if low <= 0 <= high else (left if difference > 0 else right)
            comparisons.append(
                {
                    "left": left,
                    "right": right,
                    "metric": metric,
                    "difference_left_minus_right": difference,
                    "ci_95_low": low,
                    "ci_95_high": high,
                    "outcome": outcome,
                }
            )
    return comparisons


def kendall_tau(first: Sequence[int], second: Sequence[int]) -> float:
    common = [item for item in first if item in set(second)]
    if len(common) < 2:
        return 0.0
    second_positions = {item: index for index, item in enumerate(second)}
    concordant = discordant = 0
    for left_index in range(len(common)):
        for right_index in range(left_index + 1, len(common)):
            if second_positions[common[left_index]] < second_positions[common[right_index]]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 0.0


def stability_metrics(
    primary: Sequence[dict[str, Any]],
    stability: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    first_primary = {
        row["query_id"]: row
        for row in primary
        if row.get("phase") == "benchmark" and row.get("repetition") == 0
    }
    second = {row["query_id"]: row for row in stability if row.get("phase") == "stability"}
    ids = sorted(set(first_primary) & set(second))
    taus = [kendall_tau(first_primary[q]["ranking"], second[q]["ranking"]) for q in ids]
    top1_changes = sum(
        first_primary[q].get("ranking", [None])[0:1] != second[q].get("ranking", [None])[0:1]
        for q in ids
    )
    return {"queries": len(ids), "kendall_tau_mean": _mean(taus), "top1_changes": top1_changes}


def build_metric_table(
    *,
    dataset: Sequence[dict[str, Any]],
    dataset_hash: str,
    records_by_arm: dict[str, list[dict[str, Any]]],
    stability_by_arm: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    metrics_by_arm = {
        arm: arm_metrics(dataset, records)
        for arm, records in sorted(records_by_arm.items())
    }
    costs: dict[str, Any] = {
        "baseline": {"value": 0.0, "unit": "USD per 1K queries"},
        "aws": {
            "value": 1.0,
            "unit": "USD per 1K queries",
            "source": "AWS Price List Bulk API, publication 2026-07-23",
        },
        "gcp": {"value": None, "unit": "USD per 1K queries", "status": "unverified"},
        "qwen": {"value": None, "unit": "local compute", "status": "wall-clock/VRAM"},
    }
    for arm, values in metrics_by_arm.items():
        values["cost_per_1k"] = costs.get(arm, {"value": None, "status": "unknown"})
    table: dict[str, Any] = {
        "dataset_sha256": dataset_hash,
        "candidate_recall_at_30": _mean([row["candidate_recall_at_30"] for row in dataset]),
        "arms": metrics_by_arm,
        "comparisons": comparison_table(metrics_by_arm, [row["query_id"] for row in dataset]),
    }
    if stability_by_arm:
        table["stability"] = {
            arm: stability_metrics(records_by_arm.get(arm, []), records)
            for arm, records in sorted(stability_by_arm.items())
        }
    return table


def write_metric_table(path: Path, table: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_report(
    path: Path,
    *,
    table: dict[str, Any],
    metadata: dict[str, Any],
    omissions: dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ORQ-22 reranking benchmark",
        "",
        f"- Dataset SHA-256: `{table['dataset_sha256']}`",
        f"- Measurement window: {metadata.get('measurement_window', 'not run')}",
        f"- Host: {metadata.get('host', 'not recorded')}",
        f"- GCP region/location: {metadata.get('gcp_location', 'global')}",
        f"- AWS region: {metadata.get('aws_region', 'ca-central-1')}",
        f"- Candidate recall@30 ceiling: {table['candidate_recall_at_30']:.4f}",
        f"- AWS pacing finding: {_AWS_THROTTLE_FINDING}",
        "- Cross-provider latency is indicative only and is not a ranking criterion.",
        "- Relevant means grade >= 1 for MRR@10 and HitRate@5; NDCG@10 uses grades 0/1/2.",
        "",
        "## Metric table",
        "",
        "| Arm | NDCG@10 | MRR@10 | HitRate@5 | p50 ms | p95 ms | samples | error rate | cost / 1K |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm, values in table["arms"].items():
        aggregate = values["aggregate"]
        latency = values["latency_ms"]
        cost = values["cost_per_1k"]
        cost_text = str(cost.get("value")) if cost.get("value") is not None else cost.get("status", "unverified")
        if cost.get("source"):
            cost_text = f"{cost_text} ({cost['source']})"
        arm_label = f"aws (errors at pacing {metadata.get('aws_pacing_s', 15.0)}s)" if arm == "aws" else arm
        lines.append(
            f"| {arm_label} | {aggregate['ndcg_at_10']:.4f} | {aggregate['mrr_at_10']:.4f} | "
            f"{aggregate['hit_rate_at_5']:.4f} | {_fmt(latency['p50'])} | {_fmt(latency['p95'])} | "
            f"{latency['samples']} | {values['error_rate']:.4f} | {cost_text} |"
        )
    lines.extend(["", "## Language splits", ""])
    for arm, values in table["arms"].items():
        lines.append(f"### {arm}")
        lines.append("")
        lines.append("| Language | NDCG@10 | MRR@10 | HitRate@5 |")
        lines.append("|---|---:|---:|---:|")
        for language, split in values["by_language"].items():
            lines.append(
                f"| {language} | {split['ndcg_at_10']:.4f} | {split['mrr_at_10']:.4f} | "
                f"{split['hit_rate_at_5']:.4f} |"
            )
        lines.append("")
    lines.extend(["## Programmatic paired-bootstrap decisions", ""])
    lines.append("| Left | Right | Metric | Difference | 95% CI | Outcome |")
    lines.append("|---|---|---|---:|---|---|")
    for comparison in table["comparisons"]:
        lines.append(
            f"| {comparison['left']} | {comparison['right']} | {comparison['metric']} | "
            f"{comparison['difference_left_minus_right']:.4f} | "
            f"[{comparison['ci_95_low']:.4f}, {comparison['ci_95_high']:.4f}] | "
            f"{comparison['outcome']} |"
        )
    managed = [
        row
        for row in table["comparisons"]
        if {row["left"], row["right"]} == {"aws", "gcp"}
    ]
    if managed:
        winners = {row["outcome"] for row in managed if row["outcome"] != "tie"}
        lines.extend(["", "## Recommendation", ""])
        if not winners:
            lines.append(
                "AWS and GCP tie on every pre-registered quality metric. Retain the ADR-006 "
                "incumbent AWS backend for the production follow-up; this benchmark provides no "
                "quality evidence for a provider switch."
            )
        elif len(winners) == 1:
            winner = next(iter(winners))
            lines.append(
                f"Select {winner.upper()} for the production follow-up: it is the only managed "
                "backend with a non-tie managed-provider outcome in the generated table."
            )
        else:
            lines.append(
                "No single managed backend wins across the pre-registered quality metrics; retain "
                "the ADR-006 incumbent AWS backend until a follow-up defines a trade-off rule."
            )
    if table.get("stability"):
        lines.extend(["", "## Backend stability (second live run, first 20 rows)", ""])
        lines.append("| Arm | Queries | Mean Kendall tau | Top-1 changes |")
        lines.append("|---|---:|---:|---:|")
        for arm, values in table["stability"].items():
            lines.append(
                f"| {arm} | {values['queries']} | {values['kendall_tau_mean']:.4f} | "
                f"{values['top1_changes']} |"
            )
    lines.extend(["", "## Omissions and limits", ""])
    if omissions:
        lines.extend(f"- {arm}: {reason}" for arm, reason in sorted(omissions.items()))
    else:
        lines.append("- No requested arm was omitted.")
    lines.extend(
        [
            "- A tie is a valid result whenever the paired bootstrap CI contains zero.",
            "- The table supports only the metric-specific outcomes shown above; it does not support "
            "a latency-based provider ranking or a shared relevance-score threshold.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _adapter(arm: str) -> tuple[RerankerPort, str]:
    if arm == "gcp":
        if not settings.reranker_gcp_project:
            raise TerminalRerankerError("GCP project is not configured", backend="gcp")
        return (
            GcpReranker(
                project_id=settings.reranker_gcp_project,
                location=settings.reranker_gcp_location,
                model=settings.reranker_gcp_model,
            ),
            settings.reranker_gcp_model,
        )
    if arm == "aws":
        return (
            AwsReranker(
                region=settings.reranker_aws_region,
                model=settings.reranker_aws_model,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                aws_session_token=settings.aws_session_token,
            ),
            settings.reranker_aws_model,
        )
    if arm == "qwen":
        if not settings.reranker_qwen_model_id:
            raise TerminalRerankerError("Qwen model ID is not configured", backend="qwen")
        return (
            QwenLocalReranker(
                model_id=settings.reranker_qwen_model_id,
                device=settings.reranker_qwen_device,
            ),
            settings.reranker_qwen_model_id,
        )
    raise ValueError(f"unknown arm: {arm}")


def _default_arms() -> list[str]:
    enabled = {
        "gcp": settings.reranking_benchmark_gcp_enabled,
        "aws": settings.reranking_benchmark_aws_enabled,
        "qwen": settings.reranking_benchmark_qwen_enabled,
    }
    return [arm for arm, value in enabled.items() if value]


async def async_main(args: argparse.Namespace) -> int:
    dataset_hash = verify_dataset_hash(args.dataset, args.dataset_sha256)
    dataset = load_dataset(args.dataset)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    omissions: dict[str, str] = {}
    omissions_path = args.results_dir / "omissions.json"
    if omissions_path.exists():
        omissions.update(json.loads(omissions_path.read_text(encoding="utf-8")))
    requested_arms = args.arms if args.arms is not None else _default_arms()

    if args.no_resume and not args.force:
        raise ValueError("--no-resume requires --force")
    if args.stability and not (args.no_resume and args.force):
        raise ValueError("--stability requires --no-resume --force")
    if "gcp" in requested_arms and args.gcp_call_budget <= 0 and not args.from_cache:
        raise ValueError("GCP arm requires a positive --gcp-call-budget")

    if not args.from_cache:
        for arm in requested_arms:
            phase = "stability" if args.stability else "benchmark"
            path = args.results_dir / (f"{arm}_stability.jsonl" if args.stability else f"{arm}.jsonl")
            store = JsonlResultStore(path)
            if args.no_resume:
                store.reset()
            try:
                adapter, model = _adapter(arm)
                rows = dataset[:20] if args.stability else dataset
                await run_arm(
                    arm=arm,
                    model=model,
                    adapter=adapter,
                    dataset=rows,
                    store=store,
                    repetitions=1 if args.stability else 3,
                    warmups=0 if args.stability else 5,
                    phase=phase,
                    pacer=Pacer(args.aws_pacing_s) if arm == "aws" else None,
                    budget=CallBudget(args.gcp_call_budget) if arm == "gcp" else None,
                )
            except TerminalRerankerError as exc:
                omissions[arm] = str(exc)
        omissions_path.write_text(json.dumps(omissions, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    records_by_arm: dict[str, list[dict[str, Any]]] = {"baseline": baseline_records(dataset)}
    for arm in ("gcp", "aws", "qwen"):
        store = JsonlResultStore(args.results_dir / f"{arm}.jsonl")
        records = store.load()
        if records:
            records_by_arm[arm] = records
    stability_by_arm: dict[str, list[dict[str, Any]]] = {}
    for arm in ("gcp", "aws", "qwen"):
        records = JsonlResultStore(args.results_dir / f"{arm}_stability.jsonl").load()
        if records:
            stability_by_arm[arm] = records

    table = build_metric_table(
        dataset=dataset,
        dataset_hash=dataset_hash,
        records_by_arm=records_by_arm,
        stability_by_arm=stability_by_arm,
    )
    write_metric_table(args.results_dir / "metrics.json", table)
    timestamps = [
        row.get("recorded_at")
        for records in records_by_arm.values()
        for row in records
        if row.get("recorded_at")
    ]
    metadata = {
        "measurement_window": f"{min(timestamps)} to {max(timestamps)}" if timestamps else "not run",
        "host": f"{platform.system()} {platform.release()} / {platform.machine()} / Python {platform.python_version()}",
        "gcp_location": settings.reranker_gcp_location,
        "aws_region": settings.reranker_aws_region,
        "aws_pacing_s": args.aws_pacing_s,
    }
    write_report(args.report, table=table, metadata=metadata, omissions=omissions)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the isolated ORQ-22 reranking benchmark.")
    parser.add_argument("--dataset", type=Path, default=Path("experiments/reranking/dataset.jsonl"))
    parser.add_argument("--dataset-sha256", type=Path, default=Path("experiments/reranking/dataset.sha256"))
    parser.add_argument("--results-dir", type=Path, default=Path("experiments/reranking/results"))
    parser.add_argument("--report", type=Path, default=Path("docs/reranking_benchmark.md"))
    parser.add_argument("--arms", nargs="*", choices=("gcp", "aws", "qwen"))
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stability", action="store_true")
    parser.add_argument("--gcp-call-budget", type=int, default=settings.reranking_benchmark_gcp_call_budget)
    parser.add_argument("--aws-pacing-s", type=float, default=settings.reranking_benchmark_aws_pacing_s)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(async_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
