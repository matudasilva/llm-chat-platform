from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from app.core.domain.provider_errors import ProviderError
from experiments.orq43_evaluation.adapter_client import dispatch
from experiments.orq43_evaluation.runner import AdmissionError, Candidate, Count, Manifest, PROTOCOL_SHA256, preflight

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

class Counter:
    def count(self, candidate, payload):
        return Count(sha256(payload).hexdigest(), 3)


def call(provider):
    location = 'us-east-1' if provider == 'bedrock' else 'us-central1'
    candidate = Candidate('test', provider, 'model', location, provider, 'fake', '1', '1', NOW + timedelta(days=1))
    manifest = Manifest('run', PROTOCOL_SHA256, (candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    return preflight(manifest, Counter(), now=NOW).calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_real_adapter_returns_synthetic_output_and_usage(provider):
    result = await dispatch(call(provider))
    assert (result.provider, result.content, result.input_tokens, result.output_tokens, result.total_tokens) == (provider, 'synthetic output', 3, 2, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_adapter_normalizes_fake_transport_errors(provider):
    with pytest.raises(ProviderError):
        await dispatch(call(provider), outcome='error')


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['payload', 'digest', 'candidate', 'identity'])
async def test_binding_mismatches_fail_closed(change):
    original = call('bedrock')
    updates = {'payload': {'payload': original.payload + b' '}, 'digest': {'payload_sha256': '0' * 64},
               'candidate': {'candidate': replace(original.candidate, model='different')}, 'identity': {'call_id': 'unknown:test'}}
    with pytest.raises(AdmissionError):
        await dispatch(replace(original, **updates[change]))


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_reserved_offline_adapter_run_and_replay_refusal(tmp_path, provider):
    import sqlite3
    from experiments.orq43_evaluation.adapter_client import run_adapter_offline
    from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger

    candidate = call(provider).candidate
    manifest = Manifest('run', PROTOCOL_SHA256, (candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    results = await run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    assert len(results) == 4
    assert all(result.provider == provider for result in results)
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select status from runs').fetchone() == ('complete',)
        assert db.execute("select count(*) from calls where status='succeeded'").fetchone() == (4,)
    with pytest.raises(LedgerError):
        await run_adapter_offline(manifest, Counter(), ledger, now=NOW)


@pytest.mark.asyncio
async def test_offline_adapter_failure_stops_remaining_calls(tmp_path):
    import sqlite3
    from experiments.orq43_evaluation.adapter_client import run_adapter_offline
    from experiments.orq43_evaluation.ledger import ReservationLedger

    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(ProviderError):
        await run_adapter_offline(manifest, Counter(), ledger, now=NOW, outcome='error')
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select status from runs').fetchone() == ('failed',)
        assert db.execute("select count(*) from calls where status='failed'").fetchone() == (4,)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_fake_transport_rejects_adapter_payload_mismatch(provider):
    from experiments.orq43_evaluation.adapter_client import _dispatch_prepared, _prepare

    planned = call(provider)
    request, config, body = _prepare(planned)
    with pytest.raises(ProviderError):
        await _dispatch_prepared(planned, (request, config, body + b' '), 'ok')


@pytest.mark.asyncio
async def test_ledger_stores_binding_for_all_prepared_adapter_bodies(tmp_path):
    import json
    import sqlite3
    from experiments.orq43_evaluation.adapter_client import _prepare, run_adapter_offline
    from experiments.orq43_evaluation.ledger import ReservationLedger

    manifest = Manifest('run', PROTOCOL_SHA256, (call('vertex').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    plan = preflight(manifest, Counter(), now=NOW)
    bindings = [(item.call_id, sha256(_prepare(item)[2]).hexdigest(), item.input_tokens, str(item.reservation_usd)) for item in plan.calls]
    serialized = json.dumps({'manifest': plan.manifest_sha256, 'adapter_payloads': bindings},
                            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    expected_hash = sha256(serialized).hexdigest()
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    await run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select manifest_hash from runs').fetchone() == (expected_hash,)
        rows = db.execute('select call_id, binding_json from call_bindings').fetchall()
    assert len(rows) == len(plan.calls)
    persisted = {call_id: json.loads(binding) for call_id, binding in rows}
    for item in plan.calls:
        binding = persisted[item.call_id]
        assert binding['manifest_sha256'] == plan.manifest_sha256
        encoded_manifest = json.dumps(binding['manifest'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        assert sha256(encoded_manifest).hexdigest() == plan.manifest_sha256
        assert binding['manifest']['candidates'][0]['input_rate'] == item.candidate.input_rate
        assert binding['manifest']['output_cap'] == manifest.output_cap
        assert binding['payload_sha256'] == item.payload_sha256
        assert binding['adapter_payload_sha256'] == sha256(_prepare(item)[2]).hexdigest()
        assert binding['provider'] == item.candidate.provider
        assert binding['model'] == item.candidate.model
    assert expected_hash != plan.manifest_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_mutated_payload_after_admission_stops_run(tmp_path, monkeypatch, provider):
    import sqlite3
    from experiments.orq43_evaluation import adapter_client
    from experiments.orq43_evaluation.ledger import ReservationLedger

    manifest = Manifest('run', PROTOCOL_SHA256, (call(provider).candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    original = adapter_client._dispatch_prepared
    calls = 0

    async def mutate_after_admission(planned, prepared, outcome):
        nonlocal calls
        calls += 1
        with sqlite3.connect(ledger.path) as db:
            assert db.execute('select status from runs').fetchone() == ('active',)
            assert db.execute("select count(*) from calls where status='dispatching'").fetchone() == (1,)
        request, config, body = prepared
        changed_request = replace(request, max_tokens=request.max_tokens - 1)
        return await original(planned, (changed_request, config, body), outcome)

    monkeypatch.setattr(adapter_client, '_dispatch_prepared', mutate_after_admission)
    with pytest.raises(ProviderError):
        await adapter_client.run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    assert calls == 1
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select status from runs').fetchone() == ('failed',)
        assert db.execute("select count(*) from calls where status='failed'").fetchone() == (4,)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_counted_body_drives_reservation_and_ceiling(tmp_path, provider):
    import json
    import sqlite3
    from experiments.orq43_evaluation.adapter_client import run_adapter_offline
    from experiments.orq43_evaluation.ledger import ReservationLedger

    class BodyCounter:
        def __init__(self):
            self.bodies = []

        def count(self, candidate, payload):
            body = json.loads(payload)
            assert ('modelId' in body) if provider == 'bedrock' else ('contents' in body)
            self.bodies.append(payload)
            return Count(sha256(payload).hexdigest(), 100)

    manifest = Manifest('run', PROTOCOL_SHA256, (call(provider).candidate,), 100, 32, '0.000527', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    counter = BodyCounter()
    with pytest.raises(AdmissionError, match='ceiling exceeded'):
        await run_adapter_offline(manifest, counter, ledger, now=NOW)
    assert len(counter.bodies) == 4
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select count(*) from runs').fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['bedrock', 'vertex'])
async def test_counted_prepared_bodies_bind_reservations(tmp_path, provider):
    import sqlite3
    from decimal import Decimal
    from experiments.orq43_evaluation.adapter_client import _prepare, run_adapter_offline
    from experiments.orq43_evaluation.ledger import ReservationLedger

    class RecordingCounter:
        def __init__(self):
            self.payloads = []

        def count(self, candidate, payload):
            self.payloads.append(payload)
            return Count(sha256(payload).hexdigest(), 77)

    manifest = Manifest('run', PROTOCOL_SHA256, (call(provider).candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    counter = RecordingCounter()
    await run_adapter_offline(manifest, counter, ledger, now=NOW)
    plan = preflight(manifest, Counter(), now=NOW)
    assert counter.payloads == [_prepare(item)[2] for item in plan.calls]
    with sqlite3.connect(ledger.path) as db:
        assert Decimal(db.execute('select reservation from runs').fetchone()[0]) == Decimal('0.000436')


@pytest.mark.asyncio
async def test_unbound_adapter_count_is_rejected_before_admission(tmp_path):
    import sqlite3
    from experiments.orq43_evaluation.adapter_client import run_adapter_offline
    from experiments.orq43_evaluation.ledger import ReservationLedger

    class UnboundCounter:
        def count(self, candidate, payload):
            return Count('0' * 64, 1)

    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(AdmissionError, match='unbound count'):
        await run_adapter_offline(manifest, UnboundCounter(), ledger, now=NOW)
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select count(*) from runs').fetchone() == (0,)

@pytest.mark.asyncio
async def test_result_evidence_is_durable_and_preserves_unknown_usage(tmp_path, monkeypatch):
    import json
    import sqlite3
    from experiments.orq43_evaluation import adapter_client
    from experiments.orq43_evaluation.ledger import ReservationLedger

    original = adapter_client._dispatch_prepared

    async def without_usage(*args):
        result = await original(*args)
        return replace(result, input_tokens=None, output_tokens=None, total_tokens=None)

    monkeypatch.setattr(adapter_client, '_dispatch_prepared', without_usage)
    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(AdmissionError, match="unknown or invalid usage"):
        await adapter_client.run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    reopened = ReservationLedger.open(ledger.path)
    with sqlite3.connect(reopened.path) as db:
        rows = db.execute('select c.status, r.evidence_json from calls c join call_results r using (run_id, call_id)').fetchall()
    assert len(rows) == 1
    for status, evidence_json in rows:
        evidence = json.loads(evidence_json)
        assert status == 'failed'
        assert evidence['content'] == 'synthetic output'
        assert [evidence[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')] == [None, None, None]
        assert 'raw' not in evidence


@pytest.mark.asyncio
async def test_failure_evidence_excludes_exception_details(tmp_path, monkeypatch):
    import json
    import sqlite3
    from experiments.orq43_evaluation import adapter_client
    from experiments.orq43_evaluation.ledger import ReservationLedger

    async def fail(*args):
        raise RuntimeError('secret-token')

    monkeypatch.setattr(adapter_client, '_dispatch_prepared', fail)
    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(RuntimeError):
        await adapter_client.run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    with sqlite3.connect(ledger.path) as db:
        status, evidence = db.execute('select c.status, r.evidence_json from calls c join call_results r using (run_id, call_id)').fetchone()
    assert status == 'failed'
    assert json.loads(evidence) == {'error': 'synthetic adapter failure'}
    assert 'secret-token' not in evidence


def test_result_write_failure_rolls_back_transition_and_refuses_replay(tmp_path):
    import sqlite3
    from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger

    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    ledger.admit('run', 'hash', '0.1', ['call'])
    ledger.mark_dispatching('run', 'call')
    with sqlite3.connect(ledger.path) as db:
        db.execute("CREATE TRIGGER reject_result BEFORE INSERT ON call_results BEGIN SELECT RAISE(ABORT, 'simulated crash'); END")
    with pytest.raises(LedgerError):
        ledger.record_outcome('run', 'call', succeeded=True, evidence={'content': 'synthetic output'})
    reopened = ReservationLedger.open(ledger.path)
    with sqlite3.connect(reopened.path) as db:
        assert db.execute('select status from calls').fetchone() == ('dispatching',)
        assert db.execute('select count(*) from call_results').fetchone() == (0,)
    with pytest.raises(LedgerError):
        reopened.mark_dispatching('run', 'call')


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('provider', 'unexpected'), ('model_version', 'unexpected'), ('prompt_version', 'unexpected')])
async def test_unexpected_result_identity_stops_before_next_call(tmp_path, monkeypatch, field, value):
    import json
    import sqlite3
    from experiments.orq43_evaluation import adapter_client
    from experiments.orq43_evaluation.ledger import ReservationLedger

    original = adapter_client._dispatch_prepared
    calls = 0

    async def altered(*args):
        nonlocal calls
        calls += 1
        return replace(await original(*args), **{field: value})

    monkeypatch.setattr(adapter_client, '_dispatch_prepared', altered)
    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(AdmissionError, match='unexpected result identity'):
        await adapter_client.run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    assert calls == 1
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select status from runs').fetchone() == ('failed',)
        assert db.execute("select count(*) from calls where status='failed'").fetchone() == (4,)
        evidence = json.loads(db.execute('select evidence_json from call_results').fetchone()[0])
    assert evidence['stop_reason'] == 'unexpected result identity'
    assert evidence[field] == value


@pytest.mark.asyncio
@pytest.mark.parametrize('usage', [(4, 2, 6), (3, 33, 36), (3, 2, 6)])
async def test_out_of_bounds_or_inconsistent_usage_stops_run(tmp_path, monkeypatch, usage):
    import json
    import sqlite3
    from experiments.orq43_evaluation import adapter_client
    from experiments.orq43_evaluation.ledger import ReservationLedger

    original = adapter_client._dispatch_prepared
    calls = 0

    async def altered(*args):
        nonlocal calls
        calls += 1
        return replace(await original(*args), input_tokens=usage[0], output_tokens=usage[1], total_tokens=usage[2])

    monkeypatch.setattr(adapter_client, '_dispatch_prepared', altered)
    manifest = Manifest('run', PROTOCOL_SHA256, (call('bedrock').candidate,), 100, 32, '1', '0.000001', 'offline-token-only-usd-per-million')
    ledger = ReservationLedger.create(tmp_path / 'ledger.sqlite', ceiling_usd='1')
    with pytest.raises(AdmissionError, match='unknown or invalid usage'):
        await adapter_client.run_adapter_offline(manifest, Counter(), ledger, now=NOW)
    assert calls == 1
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('select status from runs').fetchone() == ('failed',)
        evidence = json.loads(db.execute('select evidence_json from call_results').fetchone()[0])
    assert tuple(evidence[key] for key in ('input_tokens', 'output_tokens', 'total_tokens')) == usage


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['ok', 'error'])
async def test_bedrock_evaluator_uses_one_synthetic_sdk_send(monkeypatch, outcome):
    import socket

    from experiments.orq43_evaluation import adapter_client

    sends = []
    original = adapter_client._BedrockTransport.send

    def record(transport, request):
        sends.append(request.url)
        return original(transport, request)

    def refuse_dns(*args, **kwargs):
        pytest.fail('the offline evaluator attempted DNS resolution')

    monkeypatch.setattr(socket, 'getaddrinfo', refuse_dns)
    monkeypatch.setattr(adapter_client._BedrockTransport, 'send', record)
    if outcome == 'error':
        with pytest.raises(ProviderError):
            await dispatch(call('bedrock'), outcome=outcome)
    else:
        await dispatch(call('bedrock'), outcome=outcome)
    assert sends == ['https://offline.invalid/model/model/converse']
