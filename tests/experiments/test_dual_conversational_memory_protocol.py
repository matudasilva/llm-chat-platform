from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.dual_conversational_memory.build_dataset import build
from experiments.dual_conversational_memory.dataset import (
    DatasetError,
    deny_heldout_path,
    load_dataset,
    verify_dataset_manifest,
)
from experiments.dual_conversational_memory.protocol import (
    BudgetExceeded,
    ExternalCallLedger,
    ProtocolError,
    TraceabilityError,
    load_manifest,
)
from experiments.dual_conversational_memory.run_development import _ledger_kind_usage


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "experiments/dual_conversational_memory"


def test_manifest_is_frozen_and_heldout_is_null() -> None:
    manifest = load_manifest()

    assert manifest.payload["status"] == "frozen_operator_approved"
    assert manifest.payload["heldout"] == {
        "bundle": None,
        "hash": None,
        "path": None,
        "seed": None,
        "status": "not_generated_not_accessible",
    }
    assert manifest.call_limits == {
        "embedding_batch": 120,
        "generation": 528,
        "semantic_extraction": 144,
        "total": 792,
    }
    assert manifest.payload["execution"] == {
        "embedding_batch_size": 128,
        "external_timeout_seconds": 60,
        "generation_concurrency": 4,
        "semantic_extraction_concurrency": 1,
    }
    assert manifest.payload["protocol"]["retrieval_profile_selection"][
        "primary_unit"
    ] == "source_event_id"


def test_dataset_build_is_deterministic_and_never_creates_heldout(tmp_path: Path) -> None:
    first = build(output_dir=tmp_path)
    first_bytes = {
        name: (tmp_path / name).read_bytes()
        for name in ("authoring.jsonl", "development.jsonl", "dataset-manifest.json")
    }
    second = build(output_dir=tmp_path)

    assert first == second
    assert all((tmp_path / name).read_bytes() == content for name, content in first_bytes.items())
    assert not any("heldout" in path.name.casefold() for path in tmp_path.iterdir())
    assert second["heldout"] == {
        "bundle": None,
        "hash": None,
        "path": None,
        "seed": None,
        "status": "not_generated_not_accessible",
    }


def test_materialized_dataset_matches_approved_counts_and_scope() -> None:
    manifest = load_manifest()
    dataset_manifest = verify_dataset_manifest(
        PACKAGE / "data/dataset-manifest.json",
        development_manifest_sha256=manifest.sha256,
    )

    authoring = load_dataset(PACKAGE / "data/authoring.jsonl", expected_split="authoring")
    development = load_dataset(PACKAGE / "data/development.jsonl", expected_split="development")

    assert len(authoring) == dataset_manifest["authoring"]["conversations"] == 4
    assert len(development) == dataset_manifest["development"]["conversations"] == 12
    assert sum(len(item.evaluations) for item in authoring) == 16
    assert sum(len(item.evaluations) for item in development) == 48
    assert {item.tenant_id for item in development} != {item.tenant_id for item in authoring}


def test_dataset_gold_provenance_and_fallback_labels_are_deterministic() -> None:
    fixtures = load_dataset(PACKAGE / "data/development.jsonl", expected_split="development")

    for fixture in fixtures:
        ambiguous = next(item for item in fixture.evaluations if "ambiguous_deictic" in item.slices)
        assert ambiguous.fallback_required is True
        assert ambiguous.b_answerable is True
        assert ambiguous.fallback_rationale == "deictic_broad_replay"
        for message_id in ambiguous.gold_source_message_ids:
            source_event = next(
                event for event in fixture.events if message_id in {message.message_id for message in event.messages}
            )
            assert source_event.event_id in ambiguous.gold_source_event_ids


def test_heldout_split_and_path_are_rejected() -> None:
    with pytest.raises(ProtocolError, match="held-out"):
        load_dataset(PACKAGE / "data/development.jsonl", expected_split="heldout")
    with pytest.raises(ProtocolError, match="held-out"):
        deny_heldout_path(Path("isolated/heldout/bundle.json"))


def test_dataset_manifest_rejects_non_null_heldout(tmp_path: Path) -> None:
    manifest = load_manifest()
    build(output_dir=tmp_path)
    path = tmp_path / "dataset-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["heldout"]["seed"] = "forbidden"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="held-out"):
        verify_dataset_manifest(path, development_manifest_sha256=manifest.sha256)


def test_call_ledger_stops_at_generation_limit(tmp_path: Path) -> None:
    manifest = load_manifest()
    ledger = ExternalCallLedger(
        tmp_path / "calls.jsonl",
        run_id="test-run",
        manifest=manifest,
        origin_attestation={"expected_commit": manifest.expected_commit},
    )
    for index in range(528):
        call = ledger.reserve(kind="generation", model="gpt-4o-mini", step_id=str(index))
        ledger.succeeded(call, input_tokens=1, output_tokens=1)

    with pytest.raises(BudgetExceeded, match="generation"):
        ledger.reserve(kind="generation", model="gpt-4o-mini")
    assert ledger.counts()["generation"] == 528


def test_call_ledger_rejects_unknown_outcome_on_resume(tmp_path: Path) -> None:
    manifest = load_manifest()
    path = tmp_path / "calls.jsonl"
    ledger = ExternalCallLedger(
        path,
        run_id="first",
        manifest=manifest,
        origin_attestation={"expected_commit": manifest.expected_commit},
    )
    ledger.reserve(kind="embedding_batch", model="text-embedding-3-small")

    with pytest.raises(TraceabilityError, match="unknown outcome"):
        ExternalCallLedger(
            path,
            run_id="second",
            manifest=manifest,
            origin_attestation={"expected_commit": manifest.expected_commit},
        )


def test_missing_billable_usage_is_unavailable_not_zero(tmp_path: Path) -> None:
    manifest = load_manifest()
    path = tmp_path / "calls.jsonl"
    ledger = ExternalCallLedger(
        path,
        run_id="test-run",
        manifest=manifest,
        origin_attestation={"expected_commit": manifest.expected_commit},
    )
    call = ledger.reserve(
        kind="semantic_extraction",
        model="gpt-4o-mini",
        step_id="event-1",
    )
    ledger.succeeded(
        call,
        input_tokens=None,
        output_tokens=None,
        duration_ms=12.5,
    )

    usage = _ledger_kind_usage(path, "semantic_extraction")

    assert usage["usage_complete"] is False
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None
    assert ledger.summary()["duration_ms_by_kind"]["semantic_extraction"] == [12.5]
