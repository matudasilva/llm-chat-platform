"""Isolated ORQ-43 execution. Estimates do not guarantee provider charges."""
import asyncio
import json
import os
import stat
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import boto3
from botocore.config import Config

from app.core.providers.bedrock_provider import BedrockProvider
from app.core.providers.vertex_provider import VertexProvider
from .adapter_client import _prepare
from .ledger import ReservationLedger
from .runner import AdmissionError, Count, PlannedCall, preflight

_VERTEX_EVIDENCE = Path(__file__).with_name('vertex_count_evidence.json')
_ORIGINAL_BINDING_SHA256 = 'bf9ccac3ac3d628d01f6027ad0bb2c6260672562588c71f22f76d4648b5a9385'
_ORIGINAL_MANIFEST_SHA256 = '4fd16f7be5c5dc8db8b10296bd290bac9239898ddad7e2718987461b045df197'
_ORIGINAL_RESULTS_SHA256 = 'a97bc098c2d7d89d3e8e45788b7edd6bb41a37199ff7db7274488d7b1a2eeeaf'
_VERTEX_SHA256 = '4b7c7ecc70caaecd4fc7cd0840324754a7634de7b841c31f4eb1702a5ab7ab8a'
_NEMOTRON = {
    'CHAT-EN-01': (96, 'dab03402f045e5e2234c66750c9b9745c3eefbe0cc2341402b42d4295e2a7874'),
    'CHAT-ES-01': (99, '8353428515ddb744561425d5a3459568b658755c8aebf416fd5778122b69255d'),
    'RAG-EN-01': (121, 'd08a14ed55825c6a20d97238942749c91d3c4ff6232c7dfe0def7860f98382b6'),
    'RAG-ES-01': (136, '04bef92d6ee3adb97e176399c64eba2aa85c6facd133bd60f0758c1631ad089b'),
}
_IDENTITIES = {
    ('bedrock', 'nvidia.nemotron-nano-3-30b', 'us-east-1', 'bedrock'): ('0.06', '0.24'),
    ('vertex', 'gemini-3.5-flash-lite', 'global', 'vertex'): ('0.30', '2.50'),
}


@dataclass(frozen=True)
class LocalBinding:
    """Local account identifiers; never log or include them in exception text."""
    aws_account_id: str
    vertex_project_id: str


def prepare_local(manifest, binding: LocalBinding, *, now):
    """Check pinned inputs and return an offline plan, without network or writes.

    Binding hashes identify the intended accounts but do not verify credentials.
    Counts are observed or local estimates, not upper bounds on live metering.
    """
    if (type(binding) is not LocalBinding or type(binding.aws_account_id) is not str
            or re.fullmatch(r'[0-9]{12}', binding.aws_account_id) is None
            or type(binding.vertex_project_id) is not str
            or re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', binding.vertex_project_id) is None):
        raise AdmissionError('invalid account binding')
    try:
        candidates = manifest.candidates
        identities = {(c.provider, c.model, c.location, c.adapter) for c in candidates}
        if len(candidates) != 2 or identities != set(_IDENTITIES):
            raise AdmissionError('candidate identity mismatch')
        if manifest.input_cap != 4000 or manifest.output_cap != 512:
            raise AdmissionError('token configuration mismatch')
        for candidate in candidates:
            identity = (candidate.provider, candidate.model, candidate.location, candidate.adapter)
            if (candidate.input_rate, candidate.output_rate) != _IDENTITIES[identity]:
                raise AdmissionError('pricing assumptions mismatch')
    except (AttributeError, TypeError):
        raise AdmissionError('invalid manifest') from None
    evidence_bytes = _VERTEX_EVIDENCE.read_bytes()
    if sha256(evidence_bytes).hexdigest() != _VERTEX_SHA256:
        raise AdmissionError('count evidence mismatch')
    evidence = json.loads(evidence_bytes)
    prepared = []
    class Counter:
        def count(self, candidate, payload):
            call_id, item = prepared[-1]
            case = call_id.rsplit(':', 1)[0]
            if candidate.provider == 'bedrock':
                count, digest = _NEMOTRON[case]
                if sha256(payload).hexdigest() != digest:
                    raise AdmissionError('Nemotron payload mismatch')
            else:
                body = json.loads(payload)
                projection = {'contents': body['contents']}
                if 'systemInstruction' in body:
                    projection['systemInstruction'] = body['systemInstruction']
                data = json.dumps(projection, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
                record = evidence['cases'][case]
                if sha256(data).hexdigest() != record['request_body_sha256']:
                    raise AdmissionError('Vertex payload mismatch')
                count = record['input_tokens']
            return Count(sha256(payload).hexdigest(), count)
    def prepare(call_id, candidate, payload, digest):
        item = _prepare(PlannedCall(call_id, candidate, payload, digest, 0, Decimal(0)))
        prepared.append((call_id, item))
        return item[2]
    plan = preflight(manifest, Counter(), now=now, _count_payload=prepare)
    account_bindings = {
        'aws_account_sha256': sha256(binding.aws_account_id.encode()).hexdigest(),
        'vertex_project_sha256': sha256(binding.vertex_project_id.encode()).hexdigest(),
    }
    bound_record = {'manifest_sha256': plan.manifest_sha256,
                    'account_bindings': account_bindings,
                    'adapter_payloads': [(call_id, sha256(item[2]).hexdigest())
                                         for call_id, item in prepared]}
    account_bindings['binding_sha256'] = sha256(json.dumps(
        bound_record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return plan, account_bindings


def private_ledger(path, *, create: bool, ceiling_usd=None):
    """Open a ledger only inside an existing, owner-private directory.

    The directory protects SQLite journal files as well as the database. The
    ledger still independently rejects filesystems other than verified ext4.
    """
    path = Path(path).absolute()
    parent = path.parent
    st = parent.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700 or parent.resolve() != parent):
        raise AdmissionError('ledger directory must be private and owned by the current user')
    if create:
        if ceiling_usd is None:
            raise AdmissionError('ledger estimate ceiling required')
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        os.fchmod(fd, 0o600)
        created = os.fstat(fd)
        os.close(fd)
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
        raise AdmissionError('ledger file must be private and owned by the current user')
    if create:
        try:
            return ReservationLedger.create(path, ceiling_usd=ceiling_usd)
        except BaseException:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass
            raise
    if ceiling_usd is not None:
        raise AdmissionError('existing ledger ceiling is immutable')
    return ReservationLedger.open(path)


@dataclass(frozen=True, repr=False)
class AwsCredentials:
    """Explicit credentials used unchanged for both STS and Bedrock."""
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


def _aws_client(service, credentials, region):
    return boto3.client(service, region_name=region,
                        aws_access_key_id=credentials.access_key_id,
                        aws_secret_access_key=credentials.secret_access_key,
                        aws_session_token=credentials.session_token,
                        config=Config(connect_timeout=10, read_timeout=60,
                                      retries={'total_max_attempts': 1, 'mode': 'standard'}))


def _text_only_vertex_body(body):
    """Permit derivation only for the frozen, text-only Vertex request shape."""
    try:
        payload = json.loads(body)
        if set(payload) - {'contents', 'systemInstruction', 'generationConfig'}:
            return False
        if (type(payload['generationConfig']) is not dict or
                set(payload['generationConfig']) != {'maxOutputTokens', 'candidateCount'}):
            return False
        def text_parts(parts):
            return (type(parts) is list and bool(parts)
                    and all(type(part) is dict and set(part) == {'text'}
                            and type(part['text']) is str for part in parts))
        contents = payload['contents']
        if (type(contents) is not list or not contents or
                not all(type(item) is dict and set(item) == {'role', 'parts'}
                        and item['role'] in ('user', 'model') and text_parts(item['parts'])
                        for item in contents)):
            return False
        system = payload.get('systemInstruction')
        return system is None or (type(system) is dict and set(system) == {'parts'}
                                  and text_parts(system['parts']))
    except (ValueError, TypeError, KeyError):
        return False


async def run_live(manifest, counter=None, ledger=None, *, now, vertex_project_id: str,
                   binding=None, aws_credentials=None, adc_token_provider=None):
    """Reserve and execute the pinned eight calls once, sequentially.

    ADC is explicitly supplied as an async token provider. The estimate and
    ledger ceiling are not guaranteed limits on actual provider charges.
    Interrupted dispatches are ambiguous and cannot be resumed.
    """
    if (type(ledger) is not ReservationLedger or type(binding) is not LocalBinding
            or type(aws_credentials) is not AwsCredentials
            or not callable(adc_token_provider) or vertex_project_id != binding.vertex_project_id
            or type(aws_credentials.access_key_id) is not str or not aws_credentials.access_key_id
            or type(aws_credentials.secret_access_key) is not str or not aws_credentials.secret_access_key
            or (aws_credentials.session_token is not None and
                (type(aws_credentials.session_token) is not str or not aws_credentials.session_token))):
        raise AdmissionError('invalid live configuration')
    # Revalidate owner-private storage on every invocation.
    private_ledger(ledger.path, create=False)
    plan, accounts = prepare_local(manifest, binding, now=now)
    if len(plan.calls) != 8:
        raise AdmissionError('unexpected call count')
    prepared = [_prepare(call) for call in plan.calls]
    bindings = {call.call_id: {
        'manifest_sha256': plan.manifest_sha256, **accounts,
        'payload_sha256': call.payload_sha256,
        'adapter_payload_sha256': sha256(item[2]).hexdigest(),
        'provider': call.candidate.provider, 'model': call.candidate.model,
        'location': call.candidate.location, 'input_tokens': call.input_tokens,
        'reservation_usd': str(call.reservation_usd),
    } for call, item in zip(plan.calls, prepared)}
    # Both clients receive the identical explicit credentials; never fall back
    # to the ambient AWS credential chain.
    try:
        sts = _aws_client('sts', aws_credentials, 'us-east-1')
        try:
            account = sts.get_caller_identity().get('Account')
        finally:
            sts.close()
    except Exception:
        raise AdmissionError('AWS identity verification failed') from None
    if account != binding.aws_account_id:
        raise AdmissionError('AWS account binding mismatch')
    ledger.admit(plan.run_id, accounts['binding_sha256'], plan.reservation_usd,
                 (call.call_id for call in plan.calls), bindings=bindings)
    return await _execute_calls(manifest, plan.run_id, plan.calls, prepared, bindings,
                                ledger, binding, aws_credentials, vertex_project_id,
                                adc_token_provider)


async def _execute_calls(manifest, run_id, calls, prepared, bindings, ledger, binding,
                         aws_credentials, vertex_project_id, adc_token_provider):
    results = []
    for call, (request, cfg, body) in zip(calls, prepared):
        # Recheck the exact adapter body immediately before consuming the call.
        if sha256(_prepare(call)[2]).hexdigest() != bindings[call.call_id]['adapter_payload_sha256']:
            raise AdmissionError('adapter payload changed')
        ledger.mark_dispatching(run_id, call.call_id)
        try:
            if call.candidate.provider == 'bedrock':
                client = _aws_client('bedrock-runtime', aws_credentials, cfg.region)
                try:
                    result = await BedrockProvider(cfg, runtime_client=client).generate(request)
                finally:
                    client.close()
            else:
                cfg = replace(cfg, project_id=vertex_project_id, timeout_s=60)
                result = await asyncio.wait_for(
                    VertexProvider(cfg, access_token_provider=adc_token_provider).generate(request),
                    timeout=60,
                )
        except Exception:
            # A request may have reached the provider even when no response was
            # received. Preserve the durable dispatch marker as ambiguous.
            raise AdmissionError('provider outcome unknown') from None
        output_tokens = result.output_tokens
        output_source = 'reported' if type(output_tokens) is int else 'unknown'
        if (output_tokens is None and call.candidate.provider == 'vertex'
                and _text_only_vertex_body(body)
                and type(result.input_tokens) is int and result.input_tokens >= 0
                and type(result.total_tokens) is int and result.total_tokens >= result.input_tokens):
            output_tokens = result.total_tokens - result.input_tokens
            output_source = 'derived'
        usage = (result.input_tokens, output_tokens, result.total_tokens)
        valid = (result.provider == call.candidate.provider
                 and result.prompt_version == cfg.prompt_version
                 and all(type(value) is int and value >= 0 for value in usage)
                 and result.input_tokens <= manifest.input_cap
                 and output_tokens <= manifest.output_cap
                 and result.total_tokens == result.input_tokens + output_tokens)
        # Configured model is not proof of a provider-reported model identity.
        source = (result.raw or {}).get('model_version_source', 'configured')
        reported = result.model_version if source == 'provider' else None
        if not isinstance(reported, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', reported):
            reported = None
        content = result.content if isinstance(result.content, str) else ''
        content = content[:32768]
        for secret in (binding.aws_account_id, binding.vertex_project_id,
                       aws_credentials.access_key_id, aws_credentials.secret_access_key,
                       aws_credentials.session_token):
            if secret:
                content = content.replace(secret, '[redacted]')
        evidence = {'content': content, 'provider': call.candidate.provider,
                    'configured_model': call.candidate.model, 'reported_model': reported,
                    'model_identity_source': 'provider' if reported else 'unknown',
                    'input_tokens': result.input_tokens if type(result.input_tokens) is int else None,
                    'output_tokens': output_tokens if type(output_tokens) is int else None,
                    'reported_output_tokens': result.output_tokens if type(result.output_tokens) is int else None,
                    'output_tokens_source': output_source,
                    'total_tokens': result.total_tokens if type(result.total_tokens) is int else None,
                    'latency_ms': result.latency_ms if type(result.latency_ms) is int else None,
                    'stop_reason': None if valid else 'invalid or excessive usage'}
        ledger.record_outcome(run_id, call.call_id, succeeded=valid, evidence=evidence)
        if not valid:
            raise AdmissionError('invalid or excessive usage')
        results.append(evidence)
    ledger.finish_run(run_id)
    return tuple(results)


async def run_remaining_vertex(manifest, original_path, *, now, binding, vertex_project_id,
                               adc_token_provider):
    """Execute only the three cancelled Vertex calls using a one-shot sibling ledger.

    The original ledger is inspected read-only and is never changed. The sibling
    ledger must not already exist, including after an interrupted attempt. Cost
    figures remain estimates and do not guarantee provider charges.
    """
    if (type(binding) is not LocalBinding or vertex_project_id != binding.vertex_project_id
            or not callable(adc_token_provider)):
        raise AdmissionError('invalid continuation configuration')
    if manifest.run_id != 'orq43-authorized-20261125-01':
        raise AdmissionError('unexpected original run')
    if (manifest.ceiling_usd != '3' or manifest.rounding_usd != '0.000001'
            or manifest.billing_terms != 'offline-token-only-usd-per-million'
            or [(c.name, c.counter) for c in manifest.candidates] != [
                ('nemotron', 'local-template-estimate'), ('gemini', 'recorded-counttokens')]):
        raise AdmissionError('continuation manifest mismatch')
    plan, accounts = prepare_local(manifest, binding, now=now)
    prepared = [_prepare(call) for call in plan.calls]
    bindings = {call.call_id: {
        'manifest_sha256': plan.manifest_sha256, **accounts,
        'payload_sha256': call.payload_sha256,
        'adapter_payload_sha256': sha256(item[2]).hexdigest(),
        'provider': call.candidate.provider, 'model': call.candidate.model,
        'location': call.candidate.location, 'input_tokens': call.input_tokens,
        'reservation_usd': str(call.reservation_usd),
    } for call, item in zip(plan.calls, prepared)}
    expected_ids = [f'{case}:{provider}' for provider in ('nemotron', 'gemini')
                    for case in ('CHAT-EN-01', 'CHAT-ES-01', 'RAG-EN-01', 'RAG-ES-01')]
    if [call.call_id for call in plan.calls] != expected_ids:
        raise AdmissionError('unexpected call identities')
    original = Path(original_path).absolute()
    parent = original.parent
    st = parent.lstat()
    source = original.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700 or parent.resolve() != parent
            or not stat.S_ISREG(source.st_mode) or source.st_uid != os.geteuid()
            or stat.S_IMODE(source.st_mode) != 0o600 or source.st_nlink != 1):
        raise AdmissionError('original ledger must be private and owned')
    # Validate the exact complete initial state in a consistent read-only snapshot.
    try:
        with closing(sqlite3.connect(original.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            ReservationLedger._check_schema(db)
            ReservationLedger._check_state(db, ReservationLedger._read_ceiling(db))
            runs = db.execute('SELECT run_id, manifest_hash, reservation, status FROM runs').fetchall()
            statuses = dict(db.execute('SELECT call_id, status FROM calls WHERE run_id=?', (plan.run_id,)))
            stored = dict(db.execute('SELECT call_id, binding_json FROM call_bindings WHERE run_id=?', (plan.run_id,)))
            result_rows = db.execute('SELECT call_id, evidence_json FROM call_results WHERE run_id=? ORDER BY call_id', (plan.run_id,)).fetchall()
            result_digest = sha256(json.dumps(result_rows, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            expected_bindings = {key: {**value, 'manifest_sha256': _ORIGINAL_MANIFEST_SHA256,
                                       'binding_sha256': _ORIGINAL_BINDING_SHA256}
                                 for key, value in bindings.items()}
            if (runs != [(plan.run_id, _ORIGINAL_BINDING_SHA256, '0.005751', 'failed')]
                    or str(plan.reservation_usd) != '0.005751'
                    or statuses != {key: ('succeeded' if i < 4 else 'failed') for i, key in enumerate(expected_ids)}
                    or {row[0] for row in result_rows} != set(expected_ids[:5])
                    or result_digest != _ORIGINAL_RESULTS_SHA256 or set(stored) != set(bindings)
                    or any(json.loads(stored[key]) != value for key, value in expected_bindings.items())):
                raise AdmissionError('original ledger evidence mismatch')
    except (sqlite3.Error, ValueError, KeyError) as exc:
        raise AdmissionError('original ledger evidence invalid') from exc
    selected = plan.calls[5:]
    selected_prepared = prepared[5:]
    selected_bindings = {call.call_id: bindings[call.call_id] for call in selected}
    reservation = sum((call.reservation_usd for call in selected), Decimal(0))
    # The fixed sibling is an exclusive, durable one-shot claim; never reopen it.
    continuation = private_ledger(parent / 'authorized-20261125-01-continuation.sqlite',
                                  create=True, ceiling_usd=reservation)
    directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    continuation.admit(plan.run_id + '-vertex-continuation', accounts['binding_sha256'],
                       reservation, (call.call_id for call in selected), bindings=selected_bindings)
    return await _execute_calls(manifest, plan.run_id + '-vertex-continuation', selected,
                                selected_prepared, selected_bindings, continuation, binding,
                                AwsCredentials('', ''), vertex_project_id, adc_token_provider)
