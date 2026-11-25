import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from experiments.orq43_evaluation.adapter_client import _prepare
from experiments.orq43_evaluation.runner import CASES, Candidate, Count, Manifest, PROTOCOL_SHA256, preflight

EVIDENCE = Path(__file__).resolve().parents[2] / 'experiments/orq43_evaluation/vertex_count_evidence.json'
EXPECTED_PROTOCOL_SHA256 = 'da2023036a50ad3d08b25ea2d15edfc17ebcb7f4a832cff9c5ad9f29d18bd6ab'
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def _case_id(call_id):
    return call_id.split(':', 1)[0]


def _count_request_body(adapter_body):
    payload = json.loads(adapter_body)
    body = {'contents': payload['contents']}
    if 'systemInstruction' in payload:
        body['systemInstruction'] = payload['systemInstruction']
    return json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _candidate(model='gemini-3.5-flash-lite', location='global'):
    return Candidate('vertex-flash-lite', 'vertex', model, location, 'vertex', 'google-count-tokens',
                     '0.30', '2.50', NOW + timedelta(days=1))


class _SyntheticCounter:
    def count(self, candidate, payload):
        return Count(sha256(payload).hexdigest(), 1)


def _planned_calls(candidate):
    manifest = Manifest('count-binding-test', PROTOCOL_SHA256, (candidate,), 4000, 512,
                        '1', '0.000001', 'offline-token-only-usd-per-million')
    return preflight(manifest, _SyntheticCounter(), now=NOW).calls


def test_authorized_vertex_counts_bind_to_actual_adapter_payloads():
    _verify_evidence(EVIDENCE)


@pytest.mark.parametrize('model,location', [
    ('gemini-3.8-flash', 'global'),
    ('gemini-3.5-flash-lite', 'us-central1'),
])
def test_vertex_count_evidence_rejects_other_model_or_location(model, location):
    with pytest.raises(AssertionError):
        _verify_evidence(EVIDENCE, _candidate(model=model, location=location))


def _verify_evidence(path, candidate=None):
    evidence = json.loads(path.read_text())
    assert evidence['provider'] == 'vertex'
    assert evidence['model'] == 'gemini-3.5-flash-lite'
    assert evidence['location'] == 'global'
    assert evidence['endpoint'] == 'countTokens'
    assert evidence['fixture_protocol_sha256'] == EXPECTED_PROTOCOL_SHA256
    assert evidence['input_cap'] == 4000
    assert set(evidence['cases']) == {case_id for case_id, _ in CASES}

    candidate = _candidate() if candidate is None else candidate
    assert candidate.provider == evidence['provider']
    assert candidate.model == evidence['model']
    assert candidate.location == evidence['location']
    for planned in _planned_calls(candidate):
        case_id = _case_id(planned.call_id)
        _, _, adapter_body = _prepare(planned)
        count_body = _count_request_body(adapter_body)
        record = evidence['cases'][case_id]
        assert record['http_status'] == 200
        assert sha256(count_body).hexdigest() == record['request_body_sha256']
        assert type(record['input_tokens']) is int
        assert 0 <= record['input_tokens'] <= evidence['input_cap']


@pytest.mark.parametrize('tamper', ['digest', 'count', 'status', 'protocol'])
def test_vertex_count_evidence_rejects_tampered_records(tmp_path, tamper):
    evidence = json.loads(EVIDENCE.read_text())
    case_id = 'CHAT-EN-01'
    if tamper == 'digest':
        evidence['cases'][case_id]['request_body_sha256'] = '0' * 64
    elif tamper == 'count':
        evidence['cases'][case_id]['input_tokens'] = 4001
    elif tamper == 'status':
        evidence['cases'][case_id]['http_status'] = 503
    else:
        evidence['fixture_protocol_sha256'] = '0' * 64
    altered = tmp_path / 'evidence.json'
    altered.write_text(json.dumps(evidence))
    assert altered != EVIDENCE
    with pytest.raises(AssertionError):
        _verify_evidence(altered)
