"""Verify reservation and result state across abrupt process termination."""

import json
import multiprocessing
import os
import sqlite3
from contextlib import closing

import pytest

from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger


def _exit_during_run(path, stage):
    ledger = ReservationLedger.open(path)
    ledger.admit("run", "manifest", "0.75", ["first", "second"])
    if stage != "before_dispatch":
        ledger.mark_dispatching("run", "first")
    if stage == "after_result_commit":
        ledger.record_outcome("run", "first", succeeded=True, evidence={"content": "synthetic"})
    os._exit(23)


@pytest.mark.parametrize(
    ("stage", "expected_status", "expected_evidence"),
    [
        ("before_dispatch", "pending", None),
        ("after_dispatch_intent", "dispatching", None),
        ("after_result_commit", "succeeded", {"content": "synthetic"}),
    ],
)
def test_process_exit_retains_reservation_and_blocks_run_replay(
    tmp_path, stage, expected_status, expected_evidence
):
    path = tmp_path / "ledger.sqlite"
    ReservationLedger.create(path, ceiling_usd="1")
    process = multiprocessing.get_context("spawn").Process(
        target=_exit_during_run, args=(path, stage)
    )
    process.start()
    try:
        process.join(timeout=10)
        assert process.exitcode == 23
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()

    reopened = ReservationLedger.open(path)
    with closing(sqlite3.connect(path)) as db:
        run = db.execute("SELECT reservation, status FROM runs WHERE run_id='run'").fetchone()
        call = db.execute("SELECT status FROM calls WHERE call_id='first'").fetchone()
        result = db.execute("SELECT evidence_json FROM call_results WHERE call_id='first'").fetchone()
    assert run == ("0.75", "active")
    assert call == (expected_status,)
    assert (json.loads(result[0]) if result else None) == expected_evidence

    with pytest.raises(LedgerError, match="replay refused"):
        reopened.admit("run", "manifest", "0.75", ["first", "second"])
    with pytest.raises(LedgerError, match="another run is active"):
        reopened.admit("another", "manifest", "0.01", ["other"])
