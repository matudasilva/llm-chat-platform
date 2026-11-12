"""Independent integration control for actual shared retry-handler registration.

The first run expected the superseded double-wrap defect, but the author fixed
the shared working tree before that probe ran; probe.xml retains that chronology.
The current assertion verifies one event using the actual harness context.
"""
import logging

from experiments.production_graduation.gate_validation.controlled_latency_profile import Profiler, install_profile


def test_shared_application_attempt_handler_emits_one_profile_event():
    profiler = Profiler(lambda: 'independent-local-request')
    install_profile(profiler, 'c1')
    from experiments.production_graduation.gate_validation import capture
    logger = logging.getLogger('app.core.providers.bedrock_provider')
    with capture.application_attempts():
        handlers = [h for h in logger.handlers if type(h).__qualname__ == 'application_attempts.<locals>.Attempts']
        assert len(handlers) == 1
        record = logging.makeLogRecord({'msg': 'provider.request', 'attempt': 1})
        handlers[0].emit(record)  # One real handler invocation, no provider/API call.
    emissions = [e for e in profiler.events if e['label'] == 'harness.application_attempts.emit']
    assert profiler.valid
    assert len(emissions) == 1
    assert emissions[0]['parent_label'] is None
