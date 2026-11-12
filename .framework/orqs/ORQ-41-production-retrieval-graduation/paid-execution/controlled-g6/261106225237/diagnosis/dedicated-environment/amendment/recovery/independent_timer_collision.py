"""Read-only review counterexample: fake backend only, no host operations."""
import importlib.util
from pathlib import Path
import tempfile

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('reviewed_fake', HERE / 'test_admin_recovery.py')
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)
m = test.m


class ForeignTimer(test.Fake):
    def arm(self):
        # Exact production arm precondition; the fake author's arm omits it.
        m.require(not self.armed(), 'Existing recovery timer')
        super().arm()


with tempfile.TemporaryDirectory() as tmp:
    backend = ForeignTimer(Path(tmp) / '261110000001')
    # A pre-existing unrelated timer is not part of snapshot/baseline.
    backend.timer_active = True
    store = m.prepare(backend.state, backend)
    try:
        m.apply(store, backend)
    except RuntimeError as exc:
        assert str(exc) == 'Existing recovery timer'
    else:
        raise AssertionError('Application unexpectedly accepted collision')
    assert not backend.timer_active
    assert backend.calls == ['reload', 'disarm']
    assert m.validate_log(store.records())[2] == 'done'
    print('REPRODUCED: refused foreign watchdog nevertheless stopped; journal done')
