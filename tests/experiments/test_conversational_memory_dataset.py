from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.conversational_memory.dataset import (
    DatasetError,
    load_dataset,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "experiments/conversational_memory/data"


def test_frozen_dataset_hashes_match_manifest() -> None:
    manifest = json.loads((DATA / "dataset_manifest.json").read_text(encoding="utf-8"))
    for split in ("development", "heldout"):
        path = DATA / manifest[split]["path"]
        fixtures = load_dataset(path, expected_split=split)
        assert sha256_file(path) == manifest[split]["sha256"]
        assert len(fixtures) == 8
        assert sum(len(fixture.evaluations) for fixture in fixtures) == 24


def test_dataset_is_synthetic_bilingual_and_multi_tenant() -> None:
    fixtures = load_dataset(DATA / "development.jsonl", expected_split="development")
    assert all(fixture.synthetic for fixture in fixtures)
    assert {fixture.language for fixture in fixtures} == {"en", "es"}
    assert len({fixture.tenant_id for fixture in fixtures}) == 2
    assert len({fixture.conversation_id for fixture in fixtures}) == len(fixtures)


def test_teacher_forced_prefix_excludes_current_and_candidate_answer() -> None:
    fixture = load_dataset(DATA / "development.jsonl", expected_split="development")[0]
    evaluation = fixture.evaluations[1]
    prefix = fixture.prefix_before(evaluation.query_message_id)
    query = fixture.message_by_id(evaluation.query_message_id)
    reference = fixture.message_by_id(evaluation.reference_answer_message_id)
    assert [message.sequence for message in prefix] == list(range(1, query.sequence))
    assert query not in prefix
    assert reference not in prefix
    assert reference.sequence == query.sequence + 1


def test_loader_rejects_cross_tenant_conversation_reuse(tmp_path: Path) -> None:
    source = DATA / "development.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    rows[1]["conversation_id"] = rows[0]["conversation_id"]
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="reused across tenants"):
        load_dataset(path, expected_split="development")


def test_loader_rejects_non_alternating_transcript(tmp_path: Path) -> None:
    row = json.loads((DATA / "development.jsonl").read_text(encoding="utf-8").splitlines()[0])
    row["messages"][1]["role"] = "user"
    # Retain the multi-tenant/bilingual dataset-wide conditions by mutating the full file.
    rows = [row, *[
        json.loads(line)
        for line in (DATA / "development.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    ]]
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="alternate"):
        load_dataset(path, expected_split="development")
