from datetime import datetime, timedelta, timezone
from hashlib import sha256
import socket
import sqlite3

import pytest

from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger
from experiments.orq43_evaluation.offline_integration import FakeDispatcher, SimulatedCrash, run_offline
from experiments.orq43_evaluation.runner import Candidate, Count, Manifest, PROTOCOL_SHA256

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


class Counter:
    def count(self, candidate, payload):
        return Count(sha256(payload).hexdigest(), 100)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket, 'socket', blocked)
    candidate = Candidate('a', 'fake', 'model', 'local', 'fake', 'fake', '2', '10', NOW + timedelta(days=1))
    manifest = Manifest('run', PROTOCOL_SHA256, (candidate,), 4000, 512, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    return manifest, ledger


def state(ledger):
    with sqlite3.connect(ledger.path) as db:
        return db.execute('SELECT reservation, status FROM runs').fetchone(), db.execute('SELECT status FROM calls ORDER BY rowid').fetchall()


def test_reserves_full_run_before_dispatch(setup, monkeypatch):
    manifest, ledger = setup
    fake = FakeDispatcher()
    original = FakeDispatcher.dispatch
    def inspect(self, *args):
        run, calls = state(ledger)
        assert run == ('0.021280', 'active')
        assert len(calls) == 4
        assert sum(row[0] == 'dispatching' for row in calls) == 1
        return original(self, *args)
    monkeypatch.setattr(FakeDispatcher, 'dispatch', inspect)
    assert len(run_offline(manifest, Counter(), ledger, fake, now=NOW)) == 4
    assert state(ledger)[0] == ('0.021280', 'complete')


def test_failure_stops_remaining_calls(setup):
    manifest, ledger = setup
    fake = FakeDispatcher(('ok', 'error'))
    with pytest.raises(RuntimeError, match='simulated'):
        run_offline(manifest, Counter(), ledger, fake, now=NOW)
    assert len(fake.dispatched) == 2
    assert state(ledger) == (('0.021280', 'failed'), [('succeeded',), ('failed',), ('failed',), ('failed',)])


def test_crash_is_ambiguous_and_restart_never_replays(setup):
    manifest, ledger = setup
    fake = FakeDispatcher(('crash',))
    with pytest.raises(SimulatedCrash):
        run_offline(manifest, Counter(), ledger, fake, now=NOW)
    assert state(ledger) == (('0.021280', 'active'), [('dispatching',), ('pending',), ('pending',), ('pending',)])
    restarted = FakeDispatcher()
    with pytest.raises(LedgerError, match='replay refused'):
        run_offline(manifest, Counter(), ReservationLedger.open(ledger.path), restarted, now=NOW)
    assert restarted.dispatched == []


def test_completed_run_cannot_be_replayed_and_nonfake_refused(setup):
    manifest, ledger = setup
    with pytest.raises(TypeError):
        run_offline(manifest, Counter(), ledger, object(), now=NOW)
    run_offline(manifest, Counter(), ledger, FakeDispatcher(), now=NOW)
    duplicate = FakeDispatcher()
    with pytest.raises(LedgerError, match='replay refused'):
        run_offline(manifest, Counter(), ledger, duplicate, now=NOW)
    assert duplicate.dispatched == []
