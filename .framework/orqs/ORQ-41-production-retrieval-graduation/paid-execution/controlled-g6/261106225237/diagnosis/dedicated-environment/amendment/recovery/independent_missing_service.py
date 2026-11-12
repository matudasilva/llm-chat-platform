"""Round-2 fake adapter probe; never runs a subprocess or host operation."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('review_fake', Path(__file__).with_name('test_admin_recovery.py'))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
m = t.m
with tempfile.TemporaryDirectory() as tmp:
    backend = t.Fake(Path(tmp) / '261110000001')
    store = m.prepare(backend.state, backend)
    token = store.manifest()['watchdog_token']
    backend.watchdog = lambda: dict(timer=dict(LoadState='loaded', Description=token,
        Transient='yes', Triggers=backend.timer + '.service'), service=None)
    original = m.subprocess.run
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        assert args == ['/usr/bin/systemctl', 'is-active', backend.timer + '.timer']
        return SimpleNamespace(returncode=0)
    m.subprocess.run = fake_run
    try:
        assert m.Systemd.armed(backend) is True
        assert len(calls) == 1
    finally:
        m.subprocess.run = original
    print('REPRODUCED: active timer accepted as armed without recovery service')
