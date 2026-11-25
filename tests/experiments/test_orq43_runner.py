from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import socket

import pytest

from experiments.orq43_evaluation.runner import (
    AdmissionError, Candidate, Count, Manifest, PROTOCOL_SHA256, preflight,
)

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)

class Counter:
    def count(self, candidate, payload):
        return Count(sha256(payload).hexdigest(), 100)

@pytest.fixture
def manifest():
    candidate = Candidate('a', 'test', 'model', 'location', 'adapter-v1', 'counter-v1', '2', '10', NOW + timedelta(days=1))
    return Manifest('run', PROTOCOL_SHA256, (candidate,), 4000, 512, '1', '0.000001', 'offline-token-only-usd-per-million')

def test_offline_fixed_cases_and_decimal_bound(manifest, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('network is forbidden')
    monkeypatch.setattr(socket, 'socket', blocked)
    plan = preflight(manifest, Counter(), now=NOW)
    assert len(plan.calls) == 4
    assert plan.reservation_usd == Decimal('0.021280')
    assert len({call.call_id for call in plan.calls}) == 4
    assert all(sha256(call.payload).hexdigest() == call.payload_sha256 for call in plan.calls)
    assert preflight(manifest, Counter(), now=NOW) == plan

def test_two_candidates_never_exceeds_eight(manifest):
    other = replace(manifest.candidates[0], name='b')
    assert len(preflight(replace(manifest, candidates=manifest.candidates + (other,)), Counter(), now=NOW).calls) == 8
    with pytest.raises(AdmissionError):
        preflight(replace(manifest, candidates=(other,) * 3), Counter(), now=NOW)

@pytest.mark.parametrize('change', [
    {'fixture_sha256': 'bad'}, {'input_cap': 4001}, {'output_cap': 513},
    {'output_cap': True}, {'ceiling_usd': 'NaN'}, {'ceiling_usd': '0.001'},
    {'billing_terms': 'unknown'}, {'rounding_usd': '0.03'},
])
def test_rejects_invalid_manifest(manifest, change):
    with pytest.raises(AdmissionError):
        preflight(replace(manifest, **change), Counter(), now=NOW)

def test_rejects_expiry_duplicate_and_rate(manifest):
    c = manifest.candidates[0]
    for candidates in ((replace(c, price_expires=NOW),), (c, c), (replace(c, input_rate='Infinity'),)):
        with pytest.raises(AdmissionError):
            preflight(replace(manifest, candidates=candidates), Counter(), now=NOW)

@pytest.mark.parametrize('count', [Count('wrong', 1), Count('wrong', 4001), None])
def test_rejects_unbound_or_missing_counter(manifest, count):
    class BadCounter:
        def count(self, candidate, payload):
            return count
    with pytest.raises(AdmissionError):
        preflight(manifest, BadCounter(), now=NOW)

def test_rejects_excess_count_even_with_correct_digest(manifest):
    class Excess:
        def count(self, candidate, payload):
            return Count(sha256(payload).hexdigest(), 4001)
    with pytest.raises(AdmissionError):
        preflight(manifest, Excess(), now=NOW)

def test_manifest_changes_are_bound(manifest):
    original = preflight(manifest, Counter(), now=NOW)
    changed = preflight(replace(manifest, ceiling_usd='2'), Counter(), now=NOW)
    assert original.manifest_sha256 != changed.manifest_sha256

def test_cases_match_frozen_protocol_source():
    import re
    from experiments.orq43_evaluation.runner import CASES, PROTOCOL

    source = PROTOCOL.read_text()
    expected = []
    for case_id, _ in CASES:
        section = source.split(f'### {case_id}\n', 1)[1].split('\n### ', 1)[0].split('\n## ', 1)[0]
        blocks = re.findall(r'```text\n(.*?)\n```', section, re.DOTALL)
        if case_id.startswith('CHAT-'):
            messages = tuple(tuple(line.split(': ', 1)) for line in blocks[0].splitlines())
        else:
            messages = (('system', blocks[0]), ('user', blocks[1]))
        expected.append((case_id, messages))
    assert tuple(expected) == CASES


def test_rejects_mutated_frozen_cases(manifest, monkeypatch):
    from experiments.orq43_evaluation import runner

    modified = list(runner.CASES)
    modified[0] = ('CHAT-EN-01', (('user', 'changed'),))
    monkeypatch.setattr(runner, 'CASES', tuple(modified))
    with pytest.raises(AdmissionError, match='frozen cases mismatch'):
        preflight(manifest, Counter(), now=NOW)


@pytest.mark.parametrize(('quantum', 'expected'), [
    ('0.0100', Decimal('0.04')),
    ('10.0', Decimal('40')),
])
def test_rounding_uses_quantum_value_not_representation(manifest, quantum, expected):
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 2
        plan = preflight(replace(manifest, rounding_usd=quantum, ceiling_usd='100'), Counter(), now=NOW)
    assert plan.reservation_usd == expected


def test_rounding_rejects_quantum_hidden_by_ambient_precision(manifest):
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 2
        with pytest.raises(AdmissionError, match='rounding quantum'):
            preflight(replace(manifest, rounding_usd='1.00001'), Counter(), now=NOW)
