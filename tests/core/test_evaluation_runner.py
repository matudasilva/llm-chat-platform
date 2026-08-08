"""ORQ-26 Tasks 4-5: the runner's guards, its verdict, and its import boundary.

Everything here is hermetic except the leakage assertion, which needs a real
corpus and so carries the `postgres` marker. The guards are tested by making
them fail: a guard that has never been observed refusing is not a guard.
"""

from __future__ import annotations

import ast
import copy
import json
import uuid
from pathlib import Path

import pytest

from experiments.evaluation.run_evaluation import (
    GuardFailure,
    Registration,
    compute_verdict,
    load_golden_set,
    load_manifest,
    load_registration,
    validate_registration_payload,
)

_RUNNER = Path("experiments/evaluation/run_evaluation.py")
_REGISTRATION = Path("experiments/evaluation/registration.json")

# Modules whose presence would mean the run could make a generation or reranking
# call. `openai` is excluded from this list on purpose: the runner embeds every
# query, which is an OpenAI call by design and is the one external call the
# instrument is allowed (ADR-009 decision 1).
_FORBIDDEN_IMPORTS = (
    "app.core.domain.provider_factory",
    "app.core.domain.retrieval_pipeline",
    "app.core.domain.reranker",
    "app.core.providers.bedrock_provider",
    "app.core.providers.openai_provider",
    "app.core.providers.resilient_provider",
    "app.core.providers.aws_reranker",
    "app.core.providers.gcp_reranker",
    "app.core.providers.cascading_reranker",
)


def _payload() -> dict:
    return json.loads(_REGISTRATION.read_text(encoding="utf-8"))


def _registration(**overrides) -> Registration:
    payload = _payload()
    payload["decision_rule"]["thresholds"].update(overrides)
    return Registration(payload=payload, sha256="0" * 64, commit="1" * 40)


def test_runner_imports_no_generation_or_reranking_module() -> None:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offending = sorted(imported & set(_FORBIDDEN_IMPORTS))
    assert offending == [], f"runner imports generation/reranking modules: {offending}"


def test_the_import_check_would_catch_a_real_violation() -> None:
    # A test that only ever passes proves nothing about what it forbids.
    tree = ast.parse("from app.core.domain.provider_factory import build_provider\n")
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported & set(_FORBIDDEN_IMPORTS)


def test_registration_guard_rejects_null_thresholds() -> None:
    payload = _payload()
    payload["decision_rule"]["thresholds"]["recall_at_10_floor"] = None
    with pytest.raises(GuardFailure, match="thresholds are null"):
        validate_registration_payload(payload)


def test_registration_guard_rejects_an_unsigned_registration() -> None:
    for field in ("approved_by", "approved_at"):
        payload = _payload()
        payload[field] = None
        with pytest.raises(GuardFailure, match="unsigned"):
            validate_registration_payload(payload)


def test_the_committed_registration_passes_validation() -> None:
    validate_registration_payload(_payload())


def test_registration_guard_rejects_an_uncommitted_file(tmp_path: Path) -> None:
    # Inside the repository, so `git status --porcelain` sees it as untracked.
    # The guard must refuse before anything is measured.
    stray = Path("experiments/evaluation/.registration_guard_probe.json")
    stray.write_text(json.dumps(_payload()), encoding="utf-8")
    try:
        with pytest.raises(GuardFailure, match="modified or untracked"):
            load_registration(stray)
    finally:
        stray.unlink()


def test_manifest_guard_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GuardFailure, match="does not exist"):
        load_manifest(tmp_path / "absent.json")


@pytest.mark.parametrize("field", ["commit", "ingested_at", "document_count", "chunk_count"])
def test_manifest_guard_rejects_a_missing_field(tmp_path: Path, field: str) -> None:
    manifest = {
        "commit": "a" * 40,
        "ingested_at": "2026-08-08T00:00:00+00:00",
        "document_count": 1,
        "chunk_count": 1,
    }
    del manifest[field]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(GuardFailure, match=field):
        load_manifest(path)


def test_golden_set_guard_rejects_a_hash_mismatch(tmp_path: Path) -> None:
    mutated = tmp_path / "golden_set.jsonl"
    mutated.write_text('{"query_id": "q001"}\n', encoding="utf-8")
    with pytest.raises(GuardFailure, match="does not match the registered"):
        load_golden_set(_registration(), mutated)


def test_the_committed_golden_set_matches_the_registered_hash() -> None:
    assert len(load_golden_set(_registration())) == 60


def test_verdict_is_adequate_above_the_floor_and_inside_the_margin() -> None:
    verdict = compute_verdict(
        _registration(),
        {"recall@10": 0.72, "recall@20": 0.78, "recall@30": 0.83},
    )
    assert verdict["verdict"] == "CANDIDATE_GENERATOR_ADEQUATE"
    assert verdict["reasons"] == []


def test_verdict_is_inadequate_below_the_floor() -> None:
    verdict = compute_verdict(
        _registration(),
        {"recall@10": 0.60, "recall@20": 0.65, "recall@30": 0.70},
    )
    assert verdict["verdict"] == "CANDIDATE_GENERATOR_INADEQUATE"
    assert any("floor" in reason for reason in verdict["reasons"])


def test_verdict_is_inadequate_when_the_gap_exceeds_the_margin() -> None:
    # Above the floor, so only the depth-sensitivity clause can fire.
    verdict = compute_verdict(
        _registration(),
        {"recall@10": 0.70, "recall@20": 0.90, "recall@30": 0.95},
    )
    assert verdict["verdict"] == "CANDIDATE_GENERATOR_INADEQUATE"
    assert any("gap" in reason for reason in verdict["reasons"])


def test_verdict_reports_both_reasons_when_both_clauses_fire() -> None:
    verdict = compute_verdict(
        _registration(),
        {"recall@10": 0.50, "recall@20": 0.80, "recall@30": 0.85},
    )
    assert len(verdict["reasons"]) == 2


def test_verdict_uses_the_registered_thresholds_not_hardcoded_ones() -> None:
    # The same metrics must flip the verdict when the registration changes,
    # which is what proves the rule is read rather than baked in.
    metrics = {"recall@10": 0.70, "recall@20": 0.75, "recall@30": 0.80}
    assert compute_verdict(_registration(recall_at_10_floor=0.65), metrics)["verdict"] == (
        "CANDIDATE_GENERATOR_ADEQUATE"
    )
    assert compute_verdict(_registration(recall_at_10_floor=0.90), metrics)["verdict"] == (
        "CANDIDATE_GENERATOR_INADEQUATE"
    )


def test_verdict_carries_the_scope_note() -> None:
    verdict = compute_verdict(_registration(), {"recall@10": 0.9, "recall@20": 0.9, "recall@30": 0.9})
    assert "not a verdict on production retrieval" in verdict["scope_note"].lower()
