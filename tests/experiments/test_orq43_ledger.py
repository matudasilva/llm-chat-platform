from decimal import Decimal
from multiprocessing import Process, Queue

import pytest

from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger


def _race_admit(path, q, run_id):
    try:
        ReservationLedger.open(path).admit(
            run_id, "manifest", "0.75", ["case-a/model-a"]
        )
        q.put("admitted")
    except LedgerError:
        q.put("rejected")


def test_atomic_admission_reserves_whole_run_and_serializes_processes(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ReservationLedger.create(path, ceiling_usd="1")
    q = Queue()
    processes = [Process(target=_race_admit, args=(path, q, f"run-{n}")) for n in range(2)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(10)
        assert p.exitcode == 0
    assert sorted([q.get(timeout=2), q.get(timeout=2)]) == ["admitted", "rejected"]


def test_full_reservation_is_not_released_by_known_outcomes(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = ReservationLedger.create(path, ceiling_usd=Decimal("1.00"))
    ledger.admit("r1", "hash", "0.8", ["a", "b"])
    ledger.mark_dispatching("r1", "a")
    ledger.record_outcome("r1", "a", succeeded=True)
    ledger.mark_dispatching("r1", "b")
    ledger.record_outcome("r1", "b", succeeded=True)
    ledger.finish_run("r1")
    with pytest.raises(LedgerError, match="ceiling"):
        ledger.admit("r2", "hash2", "0.21", ["c"])


def test_crash_after_dispatch_intent_is_ambiguous_and_never_replayed(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = ReservationLedger.create(path, ceiling_usd="1")
    ledger.admit("r1", "hash", "0.5", ["a"])
    ledger.mark_dispatching("r1", "a")

    restarted = ReservationLedger.open(path)
    with pytest.raises(LedgerError):
        restarted.mark_dispatching("r1", "a")
    with pytest.raises(LedgerError, match="pending or ambiguous"):
        restarted.finish_run("r1", failed=True)
    with pytest.raises(LedgerError, match="another run"):
        restarted.admit("r2", "hash2", "0.1", ["b"])


def test_unique_run_and_call_ids_and_invalid_reservations_fail_closed(tmp_path):
    ledger = ReservationLedger.create(tmp_path / "ledger.sqlite", ceiling_usd="1")
    for amount in [0.1, "NaN", "-0.01"]:
        with pytest.raises(LedgerError):
            ledger.admit(f"r{amount}", "hash", amount, ["a"])
    with pytest.raises(LedgerError, match="duplicate call"):
        ledger.admit("r1", "hash", "0.1", ["a", "a"])
    ledger.admit("r1", "hash", "0.1", ["a"])
    with pytest.raises(LedgerError, match="already exists"):
        ledger.admit("r1", "hash", "0.1", ["b"])


def test_corrupt_existing_file_is_not_recreated(tmp_path):
    path = tmp_path / "ledger.sqlite"
    path.write_bytes(b"not sqlite")
    with pytest.raises(LedgerError, match="corrupt"):
        ReservationLedger.open(path)


def test_open_missing_state_refuses_to_create_it(tmp_path):
    path = tmp_path / "missing" / "ledger.sqlite"
    with pytest.raises(LedgerError, match="missing"):
        ReservationLedger.open(path)
    assert not path.parent.exists()


def test_admission_rejects_a_ceiling_that_changed_after_open(tmp_path):
    import sqlite3

    path = tmp_path / "ledger.sqlite"
    ledger = ReservationLedger.create(path, ceiling_usd="1")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE settings SET value='0.1' WHERE key='ceiling_usd'")
    with pytest.raises(LedgerError, match="ceiling changed"):
        ledger.admit("run", "manifest", "0.5", ["first"])


def test_failed_call_stops_pending_dispatches_atomically(tmp_path):
    ledger = ReservationLedger.create(tmp_path / "ledger.sqlite", ceiling_usd="1")
    ledger.admit("r1", "hash", "0.5", ["a", "b"])
    ledger.mark_dispatching("r1", "a")
    ledger.record_outcome("r1", "a", succeeded=False)
    with pytest.raises(LedgerError, match="no longer active"):
        ledger.mark_dispatching("r1", "b")
    with pytest.raises(LedgerError, match="no longer active"):
        ledger.finish_run("r1")


def test_create_is_race_safe_and_ceiling_is_persisted(tmp_path):
    path = tmp_path / "ledger.sqlite"
    q = Queue()

    def create(q, cap):
        try:
            ReservationLedger.create(path, ceiling_usd=cap)
            q.put("created")
        except LedgerError:
            q.put("rejected")

    processes = [Process(target=create, args=(q, "1")) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert sorted([q.get(timeout=2), q.get(timeout=2)]) == ["created", "rejected"]
    ledger = ReservationLedger.open(path)
    assert ledger.ceiling == Decimal("1")
    ledger.admit("r1", "hash", "0.8", ["a"])
    ledger.mark_dispatching("r1", "a")
    ledger.record_outcome("r1", "a", succeeded=True)
    ledger.finish_run("r1")
    with pytest.raises(LedgerError, match="ceiling"):
        ledger.admit("r2", "hash", "0.21", ["b"])
def test_ambiguous_call_blocks_other_dispatches(tmp_path):
    from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger

    ledger = ReservationLedger.create(tmp_path / "ledger.sqlite", ceiling_usd="1")
    ledger.admit("run", "manifest", "0.1", ["one", "two"])
    ledger.mark_dispatching("run", "one")
    with pytest.raises(LedgerError, match="dispatching or ambiguous"):
        ReservationLedger.open(tmp_path / "ledger.sqlite").mark_dispatching("run", "two")


def test_ceiling_calculation_does_not_round_away_small_reservations(tmp_path):
    ledger = ReservationLedger.create(tmp_path / "ledger.sqlite", ceiling_usd="100000000000")
    ledger.admit("first", "hash", "100000000000", ["one"])
    ledger.mark_dispatching("first", "one")
    ledger.record_outcome("first", "one", succeeded=True)
    ledger.finish_run("first")
    with pytest.raises(LedgerError, match="ceiling"):
        ledger.admit("second", "hash", "0.000000000000000001", ["two"])


def test_relative_path_can_be_reopened(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ReservationLedger.create("ledger.sqlite", ceiling_usd="1")
    ledger = ReservationLedger.open("ledger.sqlite")
    ledger.admit("run", "hash", "0.1", ["one"])


@pytest.mark.parametrize('table', ['settings', 'runs', 'calls', 'call_results'])
def test_open_rejects_malformed_table_before_admission(tmp_path, table):
    import sqlite3

    path = tmp_path / 'ledger.sqlite'
    ReservationLedger.create(path, ceiling_usd='1')
    with sqlite3.connect(path) as db:
        db.execute(f'DROP TABLE {table}')
        db.execute(f'CREATE TABLE {table} (unexpected TEXT)')
    with pytest.raises(LedgerError, match='schema invalid'):
        ReservationLedger.open(path)


def test_open_does_not_create_missing_results_table(tmp_path):
    import sqlite3

    path = tmp_path / 'ledger.sqlite'
    ReservationLedger.create(path, ceiling_usd='1')
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE call_results')
    with pytest.raises(LedgerError, match='schema invalid'):
        ReservationLedger.open(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='call_results'").fetchone() is None


def test_unverified_filesystem_is_rejected_before_ledger_creation(tmp_path, monkeypatch):
    from experiments.orq43_evaluation import ledger as ledger_module

    monkeypatch.setattr(ledger_module, "_mount_filesystem", lambda path: "nfs")
    path = tmp_path / "ledger.sqlite"
    with pytest.raises(LedgerError, match="filesystem is not verified"):
        ReservationLedger.create(path, ceiling_usd="1")
    assert not path.exists()


def test_symlink_ledger_path_is_rejected(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ReservationLedger.create(path, ceiling_usd="1")
    link = tmp_path / "ledger-link.sqlite"
    link.symlink_to(path)
    with pytest.raises(LedgerError, match="symlink"):
        ReservationLedger.open(link)


def test_existing_database_mount_is_verified_separately(tmp_path, monkeypatch):
    from experiments.orq43_evaluation import ledger as ledger_module

    path = tmp_path / "ledger.sqlite"
    ReservationLedger.create(path, ceiling_usd="1")
    real_mount_check = ledger_module._mount_filesystem

    def filesystem(target):
        return "nfs" if Path(target) == path else real_mount_check(target)

    from pathlib import Path
    monkeypatch.setattr(ledger_module, "_mount_filesystem", filesystem)
    with pytest.raises(LedgerError, match="filesystem is not verified"):
        ReservationLedger.open(path)


def test_sqlite_durability_pragmas_are_explicit_on_each_connection(tmp_path):
    ledger = ReservationLedger.create(tmp_path / "ledger.sqlite", ceiling_usd="1")
    with ledger._connect(create=False) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize("corruption", ["multiple_active", "over_ceiling"])
def test_open_rejects_inconsistent_persisted_reservation_state(tmp_path, corruption):
    import sqlite3

    path = tmp_path / "ledger.sqlite"
    ReservationLedger.create(path, ceiling_usd="1")
    with sqlite3.connect(path) as db:
        if corruption == "multiple_active":
            db.executemany(
                "INSERT INTO runs VALUES (?, ?, ?, 'active')",
                [("r1", "h1", "0.1"), ("r2", "h2", "0.1")],
            )
        else:
            db.executemany(
                "INSERT INTO runs VALUES (?, ?, ?, 'complete')",
                [("r1", "h1", "0.6"), ("r2", "h2", "0.6")],
            )
    with pytest.raises(LedgerError, match="multiple active|exceed approved ceiling"):
        ReservationLedger.open(path)
