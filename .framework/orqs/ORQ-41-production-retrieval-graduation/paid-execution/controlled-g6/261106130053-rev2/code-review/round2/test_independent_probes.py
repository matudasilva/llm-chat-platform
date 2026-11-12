"""Independent no-I/O controls using actual request context and native tape."""
import copy
import json
from uuid import UUID

import pytest

from app.core.observability import context_evidence as c1
from experiments.production_graduation.gate_validation.capture import Capture
from experiments.production_graduation.gate_validation.controlled_latency import candidate_evidence

REQUEST = str(UUID(int=901))
INSTANCE = str(UUID(int=902))


def retained():
    capture = Capture()
    with c1.request_evidence(INSTANCE, REQUEST) as state:
        for purpose in ('rewrite', 'primary'):
            token = c1._purpose.set(purpose)
            try:
                with c1.invocation():
                    capture.sent(json.dumps({'messages': [{'role': 'user', 'content': [{'text': purpose}]}]}),
                                 adapter='bedrock', application_attempt=1, sdk_attempt=1)
            finally:
                c1._purpose.reset(token)
    return state.snapshot(), capture.sends


def test_actual_context_and_native_capture_are_accepted_without_mutation():
    snapshot, sends = retained()
    before = copy.deepcopy((snapshot, sends))
    assert candidate_evidence([snapshot], sends, REQUEST) == INSTANCE
    assert (snapshot, sends) == before


@pytest.mark.parametrize('fault', ['drop_dispatch', 'changed_payload', 'wrong_purpose', 'bad_ordinal'])
def test_real_receipt_corruption_never_passes(fault):
    snapshot, sends = retained()
    if fault == 'drop_dispatch':
        snapshot['records'].pop(2)
    elif fault == 'changed_payload':
        sends[1]['payload_sha256'] = 'f' * 64
    elif fault == 'wrong_purpose':
        sends[1]['purpose'] = 'evaluator'
    else:
        snapshot['records'][1]['ordinal'] = True
    with pytest.raises(ValueError):
        candidate_evidence([snapshot], sends, REQUEST)


def test_actual_best_effort_context_creation_loss_fails_closed(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError('controlled observer loss')
    monkeypatch.setattr(c1, 'Evidence', unavailable)
    with c1.request_evidence(INSTANCE, REQUEST) as state:
        assert state is None
    with pytest.raises(ValueError):
        candidate_evidence([], [], REQUEST)
