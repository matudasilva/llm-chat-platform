"""All filesystem fixtures and event logs stay in temporary directories."""

import json

import pytest

from experiments.conversational_semantic_memory import events
from experiments.conversational_semantic_memory.heldout_access import (
    HeldoutSealError, assert_not_heldout_path, read_for_scan, read_metadata, seal, verify_seal,
)


@pytest.fixture
def pool(tmp_path):
    path = tmp_path / "heldout.json"
    path.write_bytes(b'{"values":["a","b"]}')
    return path, tmp_path / "events.jsonl"


def test_seal_and_audited_reads(pool):
    path, log = pool
    digest = events.file_sha256(path)
    seal(path, events_log=log)
    assert read_metadata(lambda raw: {"capacity": len(json.loads(raw)["values"])},
                         path, events_log=log) == {"capacity": 2}
    assert read_for_scan(path, events_log=log) == path.read_bytes()
    assert verify_seal(path, events_log=log) == digest
    chain = events.verify(log)
    assert [event.type for event in chain] == ["heldout_pool_sealed"] + ["heldout_pool_access"] * 3
    assert [event.payload["purpose"] for event in chain[1:]] == ["metadata", "fixture_scan", "verify_seal"]
    assert all(event.payload["sha256"] == digest for event in chain)
    assert b"timestamp" not in log.read_bytes()
    with pytest.raises(HeldoutSealError, match="already sealed"):
        seal(path, events_log=log)


@pytest.mark.parametrize("reader", [
    lambda path, log: read_for_scan(path, events_log=log),
    lambda path, log: read_metadata(lambda raw: {"capacity": 1}, path, events_log=log),
    lambda path, log: verify_seal(path, events_log=log),
])
def test_tampered_pool_fails_closed(pool, reader):
    path, log = pool
    seal(path, events_log=log)
    path.write_bytes(b"tampered")
    with pytest.raises(HeldoutSealError, match="differs"):
        reader(path, log)
    assert events.verify(log)[-1].payload["matches_seal"] is False


def test_unsealed_or_corrupt_log_fails_closed(pool):
    path, log = pool
    with pytest.raises(HeldoutSealError):
        read_for_scan(path, events_log=log)
    seal(path, events_log=log)
    log.write_text(log.read_text().replace("heldout_pool_sealed", "heldout_pool_changed"))
    with pytest.raises(events.EventLogError):
        read_for_scan(path, events_log=log)


def test_dev_runner_cannot_open_heldout_pool(pool, tmp_path):
    path, _ = pool
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(path)
    hardlink = tmp_path / "hardlink.json"
    hardlink.hardlink_to(path)
    for candidate in (path, symlink, hardlink, tmp_path / "sub" / ".." / path.name):
        with pytest.raises(HeldoutSealError, match="dev runner"):
            assert_not_heldout_path(candidate, heldout_path=path)
    assert_not_heldout_path(tmp_path / "dev.json", heldout_path=path)
