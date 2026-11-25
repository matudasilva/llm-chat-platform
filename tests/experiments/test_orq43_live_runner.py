from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import sqlite3
import json

import pytest

from app.core.domain.provider import ProviderResult
from experiments.orq43_evaluation import live_runner
from experiments.orq43_evaluation.ledger import LedgerError, ReservationLedger
from experiments.orq43_evaluation.runner import AdmissionError, Candidate, Count, Manifest, PROTOCOL_SHA256

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Counter:
    def count(self, candidate, payload):
        return Count(sha256(payload).hexdigest(), 100)


@pytest.fixture
def manifest():
    expiry = NOW + timedelta(days=1)
    candidates = (Candidate('nemotron', 'bedrock', 'nvidia.nemotron-nano-3-30b', 'us-east-1', 'bedrock', 'verified', '0.06', '0.24', expiry),
                  Candidate('gemini', 'vertex', 'gemini-3.5-flash-lite', 'global', 'vertex', 'verified', '0.30', '2.50', expiry))
    return Manifest('run', PROTOCOL_SHA256, candidates, 4000, 512, '1', '0.000001', 'offline-token-only-usd-per-million')


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr('experiments.orq43_evaluation.ledger._mount_filesystem', lambda path: 'ext4')
    tmp_path.chmod(0o700)
    return live_runner.private_ledger(tmp_path / 'ledger.sqlite', create=True, ceiling_usd='1')


def rows(ledger, sql):
    with sqlite3.connect(ledger.path) as db:
        return db.execute(sql).fetchall()


@pytest.mark.asyncio
async def test_live_entry_point_requires_configuration_before_admission_or_dispatch(manifest, ledger, monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('unexpected network call'))
    with pytest.raises(AdmissionError, match='invalid live configuration'):
        await live_runner.run_live(manifest, Counter(), ledger, now=NOW, vertex_project_id='test-project')
    assert rows(ledger, 'select count(*) from runs') == [(0,)]




def test_local_preflight_binds_pinned_cases_and_accounts(manifest):
    binding = live_runner.LocalBinding('123456789012', 'test-project')
    plan, accounts = live_runner.prepare_local(manifest, binding, now=NOW)
    assert [call.input_tokens for call in plan.calls] == [96, 99, 121, 136, 66, 67, 110, 118]
    assert len(plan.calls) == 8
    assert accounts['aws_account_sha256'] == sha256(binding.aws_account_id.encode()).hexdigest()
    assert accounts['vertex_project_sha256'] == sha256(binding.vertex_project_id.encode()).hexdigest()


@pytest.mark.parametrize('kind', ['price', 'cap', 'binding'])
def test_local_preflight_rejects_unpinned_inputs(manifest, kind):
    binding = live_runner.LocalBinding('123456789012', 'test-project')
    if kind == 'price':
        manifest = replace(manifest, candidates=(replace(manifest.candidates[0], input_rate='0'), manifest.candidates[1]))
    elif kind == 'cap':
        manifest = replace(manifest, output_cap=32)
    else:
        binding = replace(binding, aws_account_id='invalid')
    with pytest.raises(AdmissionError):
        live_runner.prepare_local(manifest, binding, now=NOW)


def test_private_ledger_rejects_shared_directory_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr('experiments.orq43_evaluation.ledger._mount_filesystem', lambda path: 'ext4')
    tmp_path.chmod(0o755)
    with pytest.raises(AdmissionError, match='directory'):
        live_runner.private_ledger(tmp_path / 'ledger.sqlite', create=True, ceiling_usd='1')
    tmp_path.chmod(0o700)
    ledger = live_runner.private_ledger(tmp_path / 'ledger.sqlite', create=True, ceiling_usd='1')
    assert ledger.path.stat().st_mode & 0o777 == 0o600
    ledger.path.chmod(0o644)
    with pytest.raises(AdmissionError, match='file'):
        live_runner.private_ledger(ledger.path, create=False)


def test_binding_digest_changes_with_project_or_account(manifest):
    def digest(account, project):
        return live_runner.prepare_local(manifest, live_runner.LocalBinding(account, project), now=NOW)[1]['binding_sha256']
    original = digest('123456789012', 'test-project')
    assert original != digest('123456789013', 'test-project')
    assert original != digest('123456789012', 'other-project')


def test_count_evidence_tampering_fails_closed(manifest, tmp_path, monkeypatch):
    evidence = tmp_path / 'count.json'
    evidence.write_bytes(live_runner._VERTEX_EVIDENCE.read_bytes() + b' ')
    monkeypatch.setattr(live_runner, '_VERTEX_EVIDENCE', evidence)
    with pytest.raises(AdmissionError, match='count evidence'):
        live_runner.prepare_local(manifest, live_runner.LocalBinding('123456789012', 'test-project'), now=NOW)


def test_local_preparation_uses_no_network(manifest, monkeypatch):
    import socket
    def refuse(*args, **kwargs):
        pytest.fail('local preparation attempted network access')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket.socket, 'connect_ex', refuse)
    live_runner.prepare_local(manifest, live_runner.LocalBinding('123456789012', 'test-project'), now=NOW)


def test_derivation_requires_text_only_body_without_tools(manifest):
    plan, _ = live_runner.prepare_local(manifest, live_runner.LocalBinding('123456789012', 'test-project'), now=NOW)
    body = live_runner._prepare(plan.calls[4])[2]
    assert live_runner._text_only_vertex_body(body)
    payload = json.loads(body)
    payload['tools'] = [{'functionDeclarations': []}]
    assert not live_runner._text_only_vertex_body(json.dumps(payload).encode())
    del payload['tools']
    payload['contents'][0]['parts'].append({'functionCall': {'name': 'tool'}})
    assert not live_runner._text_only_vertex_body(json.dumps(payload).encode())
    payload = json.loads(body)
    payload['generationConfig'] = ['maxOutputTokens', 'candidateCount']
    assert not live_runner._text_only_vertex_body(json.dumps(payload).encode())


def test_failed_ledger_create_removes_only_created_file(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    def fail(*args, **kwargs):
        raise LedgerError('unverified filesystem')
    monkeypatch.setattr(ReservationLedger, 'create', fail)
    path = tmp_path / 'ledger.sqlite'
    with pytest.raises(LedgerError):
        live_runner.private_ledger(path, create=True, ceiling_usd='1')
    assert not path.exists()


def test_private_ledger_on_actual_ext4_when_available(tmp_path):
    from experiments.orq43_evaluation.ledger import _mount_filesystem
    if _mount_filesystem(tmp_path) != 'ext4':
        pytest.skip('test directory is not on ext4')
    tmp_path.chmod(0o700)
    ledger = live_runner.private_ledger(tmp_path / 'ledger.sqlite', create=True, ceiling_usd='1')
    assert live_runner.private_ledger(ledger.path, create=False).ceiling == ledger.ceiling


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'failure', 'wrong_account', 'estimate_exceeded', 'cap_exceeded',
                                  'derived', 'derived_negative', 'derived_excessive', 'inconsistent'])
async def test_live_reservation_and_single_attempts_are_hermetic(manifest, ledger, monkeypatch, mode):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('unexpected network call'))
    sends = []
    class Client:
        def __init__(self, service):
            self.service = service
        def get_caller_identity(self):
            return {'Account': '999999999999' if mode == 'wrong_account' else '123456789012'}
        def close(self):
            pass
    def client(service, credentials, region):
        assert credentials.access_key_id == 'key'
        return Client(service)
    monkeypatch.setattr(live_runner, '_aws_client', client)
    async def generate(self, request):
        sends.append(self)
        assert rows(ledger, "select count(*) from calls where status='dispatching'") == [(1,)]
        if mode == 'failure':
            raise RuntimeError('secret error detail')
        provider = 'bedrock' if isinstance(self, live_runner.BedrockProvider) else 'vertex'
        if provider == 'vertex':
            assert self.cfg.timeout_s == 60
        input_tokens = 97 if mode == 'estimate_exceeded' and provider == 'bedrock' else 1
        if mode == 'cap_exceeded':
            input_tokens = 4001
        output = 1
        total = input_tokens + 1
        if provider == 'vertex':
            if mode in ('derived', 'derived_negative', 'derived_excessive'):
                output = None
                total = {'derived': 3, 'derived_negative': 0, 'derived_excessive': 514}[mode]
            elif mode == 'inconsistent':
                total = 3
        return ProviderResult(content='answer', provider=provider, model_version='configured',
                              prompt_version='v1', input_tokens=input_tokens, output_tokens=output,
                              total_tokens=total, latency_ms=1)
    monkeypatch.setattr(live_runner.BedrockProvider, 'generate', generate)
    monkeypatch.setattr(live_runner.VertexProvider, 'generate', generate)
    async def token():
        return 'fake'
    args = dict(now=NOW, vertex_project_id='test-project',
                binding=live_runner.LocalBinding('123456789012', 'test-project'),
                aws_credentials=live_runner.AwsCredentials('key', 'secret'), adc_token_provider=token)
    if mode in ('success', 'estimate_exceeded', 'derived'):
        results = await live_runner.run_live(manifest, ledger=ledger, **args)
        assert len(results) == len(sends) == 8
        if mode == 'estimate_exceeded':
            assert results[0]['input_tokens'] == 97
        assert all(result['reported_model'] is None for result in results)
        assert results[0]['output_tokens_source'] == 'reported'
        if mode == 'derived':
            assert results[4]['output_tokens'] == 2
            assert results[4]['reported_output_tokens'] is None
            assert results[4]['output_tokens_source'] == 'derived'
            evidence = json.loads(rows(ledger, 'select evidence_json from call_results')[4][0])
            assert evidence == results[4]
        assert rows(ledger, 'select status from runs') == [('complete',)]
        assert rows(ledger, 'select count(*) from call_bindings') == [(8,)]
        with pytest.raises(LedgerError):
            await live_runner.run_live(manifest, ledger=ledger, **args)
        assert len(sends) == 8
    elif mode in ('cap_exceeded', 'derived_negative', 'derived_excessive', 'inconsistent'):
        with pytest.raises(AdmissionError, match='invalid or excessive usage'):
            await live_runner.run_live(manifest, ledger=ledger, **args)
        assert len(sends) == (1 if mode == 'cap_exceeded' else 5)
        assert rows(ledger, "select status from runs") == [('failed',)]
        evidence = json.loads(rows(ledger, "select evidence_json from call_results")[-1][0])
        assert evidence['stop_reason'] == 'invalid or excessive usage'
        if mode == 'cap_exceeded':
            assert evidence['input_tokens'] == 4001
        if mode == 'derived_excessive':
            assert evidence['output_tokens'] == 513
            assert evidence['output_tokens_source'] == 'derived'
    elif mode == 'failure':
        with pytest.raises(AdmissionError, match='provider outcome unknown'):
            await live_runner.run_live(manifest, ledger=ledger, **args)
        assert len(sends) == 1
        assert rows(ledger, 'select status from runs') == [('active',)]
        assert rows(ledger, "select count(*) from calls where status='dispatching'") == [(1,)]
        assert rows(ledger, 'select count(*) from call_results') == [(0,)]
    else:
        with pytest.raises(AdmissionError, match='account binding mismatch'):
            await live_runner.run_live(manifest, ledger=ledger, **args)
        assert not sends
        assert rows(ledger, 'select count(*) from runs') == [(0,)]


@pytest.mark.asyncio
async def test_real_bedrock_adapter_and_sdk_make_one_send_on_503(manifest, ledger, monkeypatch):
    import boto3
    from botocore.awsrequest import AWSResponse
    from botocore.config import Config
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('unexpected network call'))
    sends = []
    class Raw:
        def stream(self, **kwargs):
            yield b'{"message":"synthetic"}'
    class Sts:
        def get_caller_identity(self):
            return {'Account': '123456789012'}
        def close(self):
            pass
    def client(service, credentials, region):
        if service == 'sts':
            return Sts()
        # Use the runner's production constructor and replace only transport.
        real = boto3.client(service, region_name=region, endpoint_url='https://offline.invalid',
                            aws_access_key_id=credentials.access_key_id,
                            aws_secret_access_key=credentials.secret_access_key,
                            aws_session_token=credentials.session_token,
                            config=Config(retries={'total_max_attempts': 1, 'mode': 'standard'}))
        def send(request):
            sends.append(request)
            return AWSResponse(request.url, 503, {'content-type': 'application/json',
                'x-amzn-errortype': 'ServiceUnavailableException'}, Raw())
        real._endpoint.http_session.send = send
        return real
    monkeypatch.setattr(live_runner, '_aws_client', client)
    async def token():
        return 'fake'
    with pytest.raises(AdmissionError, match='outcome unknown'):
        await live_runner.run_live(manifest, ledger=ledger, now=NOW, vertex_project_id='test-project',
            binding=live_runner.LocalBinding('123456789012', 'test-project'),
            aws_credentials=live_runner.AwsCredentials('key', 'secret'), adc_token_provider=token)
    assert len(sends) == 1
    assert rows(ledger, "select count(*) from calls where status='dispatching'") == [(1,)]


def test_aws_constructor_supplies_exact_credentials_and_disables_retries(monkeypatch):
    captured = {}
    def fake(service, **kwargs):
        captured.update(service=service, **kwargs)
    monkeypatch.setattr(live_runner.boto3, 'client', fake)
    live_runner._aws_client('bedrock-runtime', live_runner.AwsCredentials('key', 'secret', 'session'), 'us-east-1')
    assert captured['aws_access_key_id'] == 'key'
    assert captured['aws_secret_access_key'] == 'secret'
    assert captured['aws_session_token'] == 'session'
    assert captured['config'].retries['total_max_attempts'] == 1

    assert captured['config'].connect_timeout == 10
    assert captured['config'].read_timeout == 60


@pytest.mark.asyncio
async def test_vertex_timeout_keeps_dispatch_ambiguous(manifest, ledger, monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('unexpected network call'))
    class Client:
        def get_caller_identity(self):
            return {'Account': '123456789012'}
        def close(self):
            pass
    monkeypatch.setattr(live_runner, '_aws_client', lambda *args: Client())
    async def bedrock(self, request):
        return ProviderResult(content='answer', provider='bedrock', model_version='configured',
                              prompt_version='v1', input_tokens=1, output_tokens=1,
                              total_tokens=2, latency_ms=1)
    monkeypatch.setattr(live_runner.BedrockProvider, 'generate', bedrock)
    async def timeout(awaitable, timeout):
        assert timeout == 60
        awaitable.close()
        raise TimeoutError
    monkeypatch.setattr(live_runner.asyncio, 'wait_for', timeout)
    async def token():
        return 'fake'
    with pytest.raises(AdmissionError, match='provider outcome unknown'):
        await live_runner.run_live(manifest, ledger=ledger, now=NOW, vertex_project_id='test-project',
            binding=live_runner.LocalBinding('123456789012', 'test-project'),
            aws_credentials=live_runner.AwsCredentials('key', 'secret'), adc_token_provider=token)
    assert rows(ledger, "select count(*) from calls where status='dispatching'") == [(1,)]
    assert rows(ledger, 'select count(*) from call_results') == [(4,)]
    assert rows(ledger, 'select status from runs') == [('active',)]

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'unknown', 'tampered', 'evidence_tampered'])
async def test_remaining_vertex_is_one_shot_and_checks_original(manifest, ledger, monkeypatch, mode):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('unexpected network'))
    manifest = replace(manifest, run_id='orq43-authorized-20261125-01', ceiling_usd='3',
                       candidates=(replace(manifest.candidates[0], counter='local-template-estimate'),
                                   replace(manifest.candidates[1], counter='recorded-counttokens')))
    binding = live_runner.LocalBinding('123456789012', 'test-project')
    plan, accounts = live_runner.prepare_local(manifest, binding, now=NOW)
    prepared = [live_runner._prepare(call) for call in plan.calls]
    bindings = {call.call_id: {
        'manifest_sha256': plan.manifest_sha256, **accounts,
        'payload_sha256': call.payload_sha256,
        'adapter_payload_sha256': sha256(item[2]).hexdigest(),
        'provider': call.candidate.provider, 'model': call.candidate.model,
        'location': call.candidate.location, 'input_tokens': call.input_tokens,
        'reservation_usd': str(call.reservation_usd),
    } for call, item in zip(plan.calls, prepared)}
    ledger.admit(plan.run_id, accounts['binding_sha256'], plan.reservation_usd,
                 [call.call_id for call in plan.calls], bindings=bindings)
    for i, call in enumerate(plan.calls[:5]):
        ledger.mark_dispatching(plan.run_id, call.call_id)
        ledger.record_outcome(plan.run_id, call.call_id, succeeded=i < 4, evidence={'synthetic': True})
    with sqlite3.connect(ledger.path) as db:
        result_rows = db.execute('SELECT call_id, evidence_json FROM call_results ORDER BY call_id').fetchall()
    monkeypatch.setattr(live_runner, '_ORIGINAL_BINDING_SHA256', accounts['binding_sha256'])
    monkeypatch.setattr(live_runner, '_ORIGINAL_MANIFEST_SHA256', plan.manifest_sha256)
    monkeypatch.setattr(live_runner, '_ORIGINAL_RESULTS_SHA256', sha256(
        json.dumps(result_rows, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())
    if mode in ('tampered', 'evidence_tampered'):
        with sqlite3.connect(ledger.path) as db:
            if mode == 'tampered':
                db.execute('DELETE FROM call_results WHERE call_id=?', (plan.calls[0].call_id,))
            else:
                db.execute('UPDATE call_results SET evidence_json=? WHERE call_id=?',
                           ('{}', plan.calls[0].call_id))
    # A fresh expiry changes the manifest hash, but not the frozen semantics.
    manifest = replace(manifest, candidates=tuple(replace(c, price_expires=c.price_expires + timedelta(hours=1)) for c in manifest.candidates))
    before = ledger.path.read_bytes()
    sends = []
    async def generate(self, request):
        sends.append(request)
        if mode == 'unknown':
            raise RuntimeError('unknown')
        return ProviderResult(content='answer', provider='vertex', model_version='configured',
                              prompt_version='v1', input_tokens=1, output_tokens=1,
                              total_tokens=2, latency_ms=1)
    monkeypatch.setattr(live_runner.VertexProvider, 'generate', generate)
    async def token():
        return 'fake'
    args = dict(now=NOW, binding=binding, vertex_project_id='test-project', adc_token_provider=token)
    if mode in ('tampered', 'evidence_tampered'):
        with pytest.raises(AdmissionError):
            await live_runner.run_remaining_vertex(manifest, ledger.path, **args)
        assert not sends
    elif mode == 'unknown':
        with pytest.raises(AdmissionError, match='outcome unknown'):
            await live_runner.run_remaining_vertex(manifest, ledger.path, **args)
        assert len(sends) == 1
    else:
        results = await live_runner.run_remaining_vertex(manifest, ledger.path, **args)
        assert len(results) == len(sends) == 3
    assert ledger.path.read_bytes() == before
    if mode not in ('tampered', 'evidence_tampered'):
        with pytest.raises(FileExistsError):
            await live_runner.run_remaining_vertex(manifest, ledger.path, **args)
        assert len(sends) == (3 if mode == 'success' else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['ceiling', 'rounding', 'billing', 'name', 'counter'])
async def test_continuation_rejects_changed_manifest_semantics(manifest, ledger, field):
    manifest = replace(manifest, run_id='orq43-authorized-20261125-01', ceiling_usd='3',
                       candidates=(replace(manifest.candidates[0], counter='local-template-estimate'),
                                   replace(manifest.candidates[1], counter='recorded-counttokens')))
    if field == 'ceiling':
        manifest = replace(manifest, ceiling_usd='4')
    elif field == 'rounding':
        manifest = replace(manifest, rounding_usd='0.00001')
    elif field == 'billing':
        manifest = replace(manifest, billing_terms='other')
    elif field == 'name':
        manifest = replace(manifest, candidates=(replace(manifest.candidates[0], name='other'), manifest.candidates[1]))
    else:
        manifest = replace(manifest, candidates=(replace(manifest.candidates[0], counter='other'), manifest.candidates[1]))
    async def token():
        pytest.fail('unexpected token request')
    with pytest.raises(AdmissionError, match='manifest mismatch'):
        await live_runner.run_remaining_vertex(manifest, ledger.path, now=NOW,
            binding=live_runner.LocalBinding('123456789012', 'test-project'),
            vertex_project_id='test-project', adc_token_provider=token)
