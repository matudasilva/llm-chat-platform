from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.domain.reranker import RerankRequest, TerminalRerankerError
from app.scripts.run_reranking_benchmark import (
    CallBudget,
    JsonlResultStore,
    _invoke_with_retry,
    async_main,
    build_parser,
    emit_reranker_event,
    verify_dataset_hash,
)


class _TerminalAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, request: RerankRequest) -> list[Any]:
        self.calls += 1
        raise TerminalRerankerError("denied", backend="test", error_code="AccessDeniedException")


class _SuccessfulAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, request: RerankRequest) -> list[Any]:
        self.calls += 1
        return []


def _fixture_dataset(tmp_path: Path) -> tuple[Path, Path, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for index in range(60):
        candidates = [
            {
                "candidate_id": f"c-{index}-{candidate}",
                "document_id": f"d-{candidate}",
                "source_path": f"docs/{candidate}.md",
                "text": f"document {candidate}",
                "baseline_rank": candidate + 1,
                "rrf_score": 1.0 / (61 + candidate),
                "relevance": 2 if candidate == 0 else 0,
            }
            for candidate in range(30)
        ]
        rows.append(
            {
                "query_id": f"q{index + 1:03d}",
                "language": "en" if index % 2 == 0 else "es",
                "query": f"query {index}",
                "judgments": [{"source_path": "docs/0.md", "relevance": 2}],
                "candidate_recall_at_30": 1.0,
                "candidates": candidates,
            }
        )
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    sha_path = tmp_path / "dataset.sha256"
    sha_path.write_text(f"{digest}  dataset.jsonl\n", encoding="utf-8")
    return dataset_path, sha_path, rows


def _fixture_responses(results_dir: Path, rows: list[dict[str, Any]]) -> None:
    store = JsonlResultStore(results_dir / "gcp.jsonl")
    for row in rows:
        for repetition in range(3):
            store.append(
                {
                    "arm": "gcp",
                    "model": "fixture",
                    "phase": "benchmark",
                    "query_id": row["query_id"],
                    "language": row["language"],
                    "repetition": repetition,
                    "ranking": list(range(30)),
                    "scores": [None] * 30,
                    "latency_ms": 10.0 + repetition,
                    "error": None,
                    "recorded_at": "2026-08-04T00:00:00+00:00",
                }
            )


def test_dataset_hash_mismatch_aborts_before_execution(tmp_path: Path) -> None:
    dataset_path, sha_path, _ = _fixture_dataset(tmp_path)
    dataset_path.write_text(dataset_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dataset SHA-256 mismatch"):
        verify_dataset_hash(dataset_path, sha_path)


def test_incremental_result_store_resumes_from_persisted_keys(tmp_path: Path) -> None:
    store = JsonlResultStore(tmp_path / "results.jsonl")
    row = {"phase": "benchmark", "query_id": "q001", "repetition": 0}

    store.append(row)

    assert JsonlResultStore(store.path).keys() == {("benchmark", "q001", 0)}


async def test_terminal_error_is_not_retried() -> None:
    adapter = _TerminalAdapter()

    results, _, error = await _invoke_with_retry(
        adapter=adapter,
        request=RerankRequest(query="query", documents=("document",)),
        backend="test",
        model="fixture",
        pacer=None,
        budget=None,
        telemetry=lambda event, payload: None,
    )

    assert results == []
    assert error == "AccessDeniedException"
    assert adapter.calls == 1


async def test_gcp_zero_budget_fails_before_adapter_call() -> None:
    adapter = _SuccessfulAdapter()

    with pytest.raises(TerminalRerankerError, match="budget exhausted"):
        await _invoke_with_retry(
            adapter=adapter,
            request=RerankRequest(query="query", documents=("document",)),
            backend="gcp",
            model="fixture",
            pacer=None,
            budget=CallBudget(0),
            telemetry=lambda event, payload: None,
        )

    assert adapter.calls == 0


def test_telemetry_excludes_content_and_is_best_effort() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    emit_reranker_event(
        lambda event, payload: captured.append((event, payload)),
        "reranker.request",
        backend="gcp",
        model="model",
        candidate_count=30,
        outcome="started",
        query="secret query",
        document="secret document",
        credentials="secret credentials",
    )

    assert captured == [
        (
            "reranker.request",
            {"backend": "gcp", "model": "model", "candidate_count": 30, "outcome": "started"},
        )
    ]

    def raising_sink(event: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("telemetry unavailable")

    emit_reranker_event(raising_sink, "reranker.request", backend="gcp", query="secret")


async def test_from_cache_metric_table_is_byte_identical(tmp_path: Path) -> None:
    dataset_path, sha_path, rows = _fixture_dataset(tmp_path)
    results_dir = tmp_path / "results"
    report_path = tmp_path / "report.md"
    _fixture_responses(results_dir, rows)
    args = build_parser().parse_args(
        [
            "--dataset",
            str(dataset_path),
            "--dataset-sha256",
            str(sha_path),
            "--results-dir",
            str(results_dir),
            "--report",
            str(report_path),
            "--from-cache",
        ]
    )

    await async_main(args)
    first = (results_dir / "metrics.json").read_bytes()
    await async_main(args)
    second = (results_dir / "metrics.json").read_bytes()

    assert first == second
    table = json.loads(first)
    assert {item["outcome"] for item in table["comparisons"]} == {"tie"}
    assert table["arms"]["gcp"]["latency_ms"]["samples"] == 180


def test_production_requirements_exclude_experiment_dependencies() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    production_dependencies = (
        (repo_root / "app/requirements.txt").read_text(encoding="utf-8").lower()
        + (repo_root / "app/requirements.lock").read_text(encoding="utf-8").lower()
    )

    assert "torch" not in production_dependencies
    assert "transformers" not in production_dependencies
    assert "google-cloud-" not in production_dependencies
