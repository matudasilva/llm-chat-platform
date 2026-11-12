"""No host commands: deterministic recovery counterexamples with a fake backend."""
import base64
import copy
import importlib.util
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location('admin_recovery', Path(__file__).with_name('admin_recovery.py'))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class Crash(BaseException):
    pass


class Fake(m.Systemd):
    def __init__(self, path):
        super().__init__(path)
        self.files = dict.fromkeys((*m.UNITS, m.BENCH))
        self.values = dict.fromkeys((*m.UNITS, m.BENCH), '')
        self.active = False
        self.timer_active = False
        self.occupied = False
        self.calls = []
        self.crash_at = None
        self.error_at = None
        self.count = 0
        self.extra = ''
        self.reload_fail = False

    def checkpoint(self, operation):
        self.calls.append(operation)
        self.count += 1
        if self.count == self.crash_at:
            raise Crash(operation)
        if self.count == self.error_at:
            raise OSError('Already mutated: ' + operation)

    def identity(self, unit):
        return [123, unit, self.files[unit]] if self.files[unit] is not None else None

    def watchdog(self):
        return dict(timer=None, service=None)

    def inventory(self):
        return {'preserved': 'four unchanged containers and power', 'extra': self.extra}

    def props(self, unit):
        v = self.values[unit]
        return dict(AllowedCPUs=v, StartupAllowedCPUs='', EffectiveCPUs=v or '0-31',
                    FragmentPath=str(self.paths[unit]) if unit == m.BENCH and self.files[unit] else '',
                    DropInPaths=str(self.paths[unit]) if unit in m.UNITS and self.files[unit] else '',
                    ActiveState='active' if unit != m.BENCH or self.active else 'inactive',
                    ControlGroup='/' + unit if unit != m.BENCH or self.active else '')

    def file(self, unit):
        return self.files[unit]

    def arm(self):
        self.timer_active = True
        self.checkpoint('arm')

    def armed(self, pair_required=True):
        return self.timer_active

    def disarm(self):
        self.timer_active = False
        self.checkpoint('disarm')

    def apply_one(self, index):
        unit = m.BENCH if index == 0 else m.UNITS[index-1]
        self.files[unit] = base64.b64encode(m.UNIT_BODY if index == 0 else m.fragment(unit, '8-31')).decode()
        self.checkpoint('write:' + unit)
        self.values[unit] = '0-7' if index == 0 else '8-31'
        if index == 0:
            self.active = True
        self.checkpoint('manager:' + unit)

    def command(self, *args):
        assert args[:3] == ('/usr/bin/systemctl', 'set-property', '--runtime')
        unit = args[3]
        self.values[unit] = ''
        self.files[unit] = base64.b64encode(m.fragment(unit, '')).decode()
        self.checkpoint('reset:' + unit)
        return ''

    def remove_owned(self, unit):
        expected = base64.b64encode(m.UNIT_BODY if unit == m.BENCH else m.fragment(unit, '')).decode()
        assert self.files[unit] in (None, expected)
        self.files[unit] = None
        self.checkpoint('remove:' + unit)

    def stop_empty(self):
        self.ensure_empty()
        self.active = False
        self.values[m.BENCH] = ''
        self.checkpoint('stop')

    def ensure_empty(self):
        m.require(not self.occupied, 'NOT DRAINED')

    def reload(self):
        self.checkpoint('reload')
        if self.reload_fail:
            raise OSError('Final reload failed')


@pytest.fixture
def setup(tmp_path):
    backend = Fake(tmp_path / '261110000001')
    store = m.prepare(backend.state, backend)
    return store, backend, copy.deepcopy(backend.snapshot())


def restored(store, backend, baseline):
    m.recover(store, backend)
    assert backend.snapshot() == baseline
    assert m.validate_log(store.records())[2] == 'done'
    assert not backend.armed()
    calls = list(backend.calls)
    m.recover(store, backend)
    assert backend.calls == calls
    with pytest.raises(RuntimeError, match='Never replay'):
        m.apply(store, backend)


def test_full_apply_and_exact_restore(setup):
    store, backend, before = setup
    m.apply(store, backend)
    assert all(backend.values[u] == '8-31' for u in m.UNITS)
    restored(store, backend, before)
    assert backend.calls[-2:] == ['reload', 'disarm']


@pytest.mark.parametrize('point', range(1, 12))
def test_crash_after_each_apply_mutation(setup, point):
    store, backend, before = setup
    backend.crash_at = point
    with pytest.raises(Crash):
        m.apply(store, backend)
    backend.crash_at = None
    restored(store, backend, before)


@pytest.mark.parametrize('point', range(1, 12))
def test_nonzero_after_mutation_enters_recovery(setup, point):
    store, backend, before = setup
    backend.error_at = point
    with pytest.raises(OSError):
        m.apply(store, backend)
    backend.error_at = None
    restored(store, backend, before)


@pytest.mark.parametrize('point', range(1, 13))
def test_second_crash_during_each_restore_mutation(setup, point):
    store, backend, before = setup
    m.apply(store, backend)
    backend.crash_at = backend.count + point
    with pytest.raises(Crash):
        m.recover(store, backend)
    backend.crash_at = None
    restored(store, backend, before)


@pytest.mark.parametrize('event', ['APPLIED', 'ARMED', 'DISARMED', 'RESTORED', 'UNKNOWN'])
def test_invalid_order_fails_without_mutation(setup, event):
    store, backend, _ = setup
    store.append(event, 0 if event == 'APPLIED' else None)
    with pytest.raises(RuntimeError):
        m.recover(store, backend)
    assert not backend.calls


def test_corrupt_record_fails_closed(setup):
    store, backend, _ = setup
    (store.path / 'record-0000.json').write_bytes(b'{')
    with pytest.raises(ValueError):
        m.recover(store, backend)
    assert not backend.calls


def test_journal_gap_fails_closed(setup):
    store, backend, _ = setup
    store.append('ARM_INTENT')
    (store.path / 'record-0000.json').unlink()
    with pytest.raises(RuntimeError):
        m.recover(store, backend)
    assert not backend.calls


def test_occupied_slice_preserved(setup):
    store, backend, _ = setup
    m.apply(store, backend)
    backend.occupied = True
    calls = backend.calls[:]
    with pytest.raises(RuntimeError, match='NOT DRAINED'):
        m.recover(store, backend)
    assert backend.calls == calls and backend.active


def test_foreign_override_untouched(setup):
    store, backend, _ = setup
    m.apply(store, backend)
    backend.files[m.UNITS[0]] = 'foreign'
    calls = backend.calls[:]
    with pytest.raises(RuntimeError, match='Owned file replaced'):
        m.recover(store, backend)
    assert backend.calls == calls


def test_preservation_inventory_drift_blocks_recovery(setup):
    store, backend, _ = setup
    m.apply(store, backend)
    backend.extra = 'unrelated change'
    with pytest.raises(RuntimeError, match='inventory drift'):
        m.recover(store, backend)


def test_final_reload_failure_cannot_claim_restored(setup):
    store, backend, before = setup
    m.apply(store, backend)
    backend.reload_fail = True
    with pytest.raises(OSError):
        m.recover(store, backend)
    assert not any(r['event'] == 'RESTORED' for r in store.records())
    assert backend.armed()
    backend.reload_fail = False
    restored(store, backend, before)


def test_baseline_drift_prevents_apply(setup):
    store, backend, _ = setup
    backend.extra = 'changed'
    with pytest.raises(RuntimeError, match='Baseline drift'):
        m.apply(store, backend)
    assert not backend.calls


def test_global_maintenance_lock(setup):
    store, _, _ = setup
    with store.lock():
        with pytest.raises(BlockingIOError):
            with m.Store(store.path).lock():
                pytest.fail('Lock bypassed')


def test_baseline_fsync_failure_has_zero_host_mutations(tmp_path, monkeypatch):
    backend = Fake(tmp_path / '261110000001')
    monkeypatch.setattr(m, 'sync_dir', lambda path: (_ for _ in ()).throw(OSError('fsync')))
    with pytest.raises(OSError):
        m.prepare(backend.state, backend)
    assert not backend.calls


def test_unsupported_existing_override_rejected(tmp_path):
    backend = Fake(tmp_path / '261110000001')
    backend.files[m.UNITS[0]] = 'foreign'
    with pytest.raises(RuntimeError, match='Pre-existing'):
        m.prepare(backend.state, backend)
    assert not backend.state.exists() and not backend.calls


def test_state_symlink_rejected(setup, tmp_path):
    store, backend, _ = setup
    link = tmp_path / 'alias'
    link.symlink_to(store.path, target_is_directory=True)
    with pytest.raises(RuntimeError, match='Unsafe'):
        m.recover(m.Store(link), backend)


def test_journal_symlink_rejected(setup, tmp_path):
    store, backend, _ = setup
    original = store.path / 'record-0000.json'
    copyfile = tmp_path / 'copied'
    original.rename(copyfile)
    original.symlink_to(copyfile)
    with pytest.raises(OSError):
        m.recover(store, backend)
    assert not backend.calls


def test_atomic_publication_never_overwrites(tmp_path):
    path = tmp_path / 'record'
    m.atomic_new(path, b'first')
    with pytest.raises(FileExistsError):
        m.atomic_new(path, b'second')
    assert path.read_bytes() == b'first'


def test_live_commands_not_used(monkeypatch, setup):
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('Host command attempted'))
    store, backend, before = setup
    m.apply(store, backend)
    restored(store, backend, before)


@pytest.mark.parametrize('phase', ['apply', 'recover'])
@pytest.mark.parametrize('after', [False, True])
@pytest.mark.parametrize('point', range(1, 34))
def test_interrupt_at_durable_journal_boundary(setup, monkeypatch, phase, after, point):
    store, backend, before = setup
    if phase == 'recover':
        m.apply(store, backend)
    append = store.append
    count = 0
    def interrupted(event, value=None):
        nonlocal count
        count += 1
        if count == point and not after:
            raise Crash(event)
        append(event, value)
        if count == point and after:
            raise Crash(event)
    monkeypatch.setattr(store, 'append', interrupted)
    try:
        (m.apply if phase == 'apply' else m.recover)(store, backend)
    except Crash:
        pass
    monkeypatch.setattr(store, 'append', append)
    restored(store, backend, before)


def test_runtime_symlink_refused_without_touching_target(tmp_path):
    backend = m.Systemd(tmp_path)
    target = tmp_path / 'foreign'
    target.write_bytes(b'preserve')
    link = tmp_path / 'symlink'
    link.symlink_to(target)
    backend.paths[m.BENCH] = link
    with pytest.raises(OSError):
        m.read_regular(link)
    assert target.read_bytes() == b'preserve'


def test_previous_unrecovered_run_blocks_new_prepare(setup):
    store, backend, _ = setup
    with pytest.raises(RuntimeError, match='Previous maintenance'):
        m.prepare(store.path.parent / '261110000002', backend)
    assert not backend.calls


def test_manifest_action_drift_fails_before_host_write(setup):
    store, backend, _ = setup
    body = m.json.loads((store.path / 'baseline.json').read_bytes())
    body['data']['actions'][1]['after'] = 'unknown'
    body['hash'] = m.digest(body['data'])
    (store.path / 'baseline.json').write_bytes(m.encoded(body))
    with pytest.raises(RuntimeError, match='Manifest contract'):
        m.apply(store, backend)
    assert not backend.calls


def test_apply_lease_expiry_recovers_without_later_writes(setup, monkeypatch):
    store, backend, before = setup
    clock = iter([0, 0, 1000])
    monkeypatch.setattr(m.time, 'monotonic', lambda: next(clock))
    with pytest.raises(RuntimeError, match='lease lost'):
        m.apply(store, backend)
    assert not any('user.slice' in c for c in backend.calls)
    restored(store, backend, before)


def test_owned_file_replacement_between_read_and_unlink_is_refused(tmp_path, monkeypatch):
    backend = m.Systemd(tmp_path)
    path = tmp_path / 'owned'
    path.write_bytes(m.UNIT_BODY)
    backend.paths[m.BENCH] = path
    def read_and_replace(target):
        data, identity = original(target)
        replacement = tmp_path / 'replacement'
        replacement.write_bytes(m.UNIT_BODY)
        replacement.replace(target)
        return data, (identity[0], identity[1], 0, 0o644)
    original = m.read_regular
    monkeypatch.setattr(m, 'read_regular', read_and_replace)
    with pytest.raises(RuntimeError, match='replaced during'):
        backend.remove_owned(m.BENCH)
    assert path.read_bytes() == m.UNIT_BODY


def test_foreign_file_is_never_removed(tmp_path):
    backend = m.Systemd(tmp_path)
    path = tmp_path / 'foreign'
    path.write_bytes(b'foreign')
    backend.paths[m.BENCH] = path
    with pytest.raises(RuntimeError, match='foreign file deletion'):
        backend.remove_owned(m.BENCH)
    assert path.read_bytes() == b'foreign'


def test_systemd_apply_fixed_allowlist_and_reload_order(tmp_path, monkeypatch):
    backend = m.Systemd(tmp_path)
    calls = []
    backend.paths[m.BENCH] = tmp_path / 'unit'
    monkeypatch.setattr(m, 'atomic_new', lambda p, raw, mode: calls.append(('file', str(p), raw, mode)))
    monkeypatch.setattr(backend, 'command', lambda *args: calls.append(args))
    backend.apply_one(0)
    assert calls == [('file', str(tmp_path / 'unit'), m.UNIT_BODY, 0o644),
                     ('/usr/bin/systemctl', 'daemon-reload'),
                     ('/usr/bin/systemctl', 'start', m.BENCH)]
    calls.clear()
    for index in range(1, 5):
        backend.apply_one(index)
    assert calls == [('/usr/bin/systemctl', 'set-property', '--runtime', unit, 'AllowedCPUs=8-31')
                     for unit in m.UNITS]


@pytest.mark.parametrize('kind', ['timer', 'service'])
def test_existing_watchdog_prevents_preparation(tmp_path, kind):
    backend = Fake(tmp_path / '261110000001')
    backend.watchdog = lambda: {k: {'Description': 'foreign'} if k == kind else None
                                for k in ('timer', 'service')}
    with pytest.raises(RuntimeError, match='Recovery unit collision'):
        m.prepare(backend.state, backend)
    assert not backend.calls


def test_foreign_timer_never_disarmed_after_arm_rejects(setup, monkeypatch):
    store, backend, _ = setup
    foreign = dict(LoadState='loaded', Description='foreign', Transient='yes',
                   Triggers=backend.timer + '.service')
    # Appears after the second baseline comparison, immediately before arm.
    monkeypatch.setattr(backend, 'arm', lambda: (_ for _ in ()).throw(RuntimeError('Existing recovery unit')))
    monkeypatch.setattr(backend, 'disarm', lambda: m.Systemd.disarm(backend))
    monkeypatch.setattr(backend, 'watchdog', lambda: dict(timer=foreign, service=None))
    # Preserve the pre-application baseline check, but leave disarm on the real adapter.
    snapshot = backend.snapshot()
    snapshot['watchdog'] = dict(timer=None, service=None)
    monkeypatch.setattr(backend, 'snapshot', lambda: snapshot)
    with pytest.raises(RuntimeError, match='Foreign recovery unit'):
        m.apply(store, backend)
    assert not any(c == 'disarm' or c.startswith(('write:', 'manager:')) for c in backend.calls)
    assert not any(r['event'] == 'DISARMED' for r in store.records())


def test_owned_watchdog_checked_for_fixed_executable(setup, monkeypatch):
    store, backend, _ = setup
    token = store.manifest()['watchdog_token']
    timer = dict(LoadState='loaded', Description=token, Transient='yes',
                 Triggers=backend.timer + '.service')
    service = dict(LoadState='loaded', Description=token, Transient='yes', ExecStart='wrong')
    monkeypatch.setattr(backend, 'watchdog', lambda: dict(timer=timer, service=service))
    with pytest.raises(RuntimeError, match='Wrong recovery executable'):
        backend.verify_owned_watchdog(pair_required=True)
    service['ExecStart'] = ('{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -I '
        + str(store.path / 'helper.py') + ' recover ' + str(store.path) + ' ; ignore_errors=no ; }')
    assert backend.verify_owned_watchdog(pair_required=True)['timer'] == timer


def test_owned_timer_disarm_and_missing_timer_noop(setup, monkeypatch):
    store, backend, _ = setup
    token = store.manifest()['watchdog_token']
    units = dict(timer=dict(LoadState='loaded', Description=token, Transient='yes',
                           Triggers=backend.timer + '.service'), service=None)
    monkeypatch.setattr(backend, 'watchdog', lambda: units)
    commands = []
    monkeypatch.setattr(backend, 'command', lambda *args: commands.append(args))
    m.Systemd.disarm(backend)
    assert commands == [('/usr/bin/systemctl', 'stop', backend.timer + '.timer')]
    commands.clear()
    units['timer'] = None
    m.Systemd.disarm(backend)
    assert not commands


@pytest.mark.parametrize('missing', ['timer', 'service'])
def test_every_admission_requires_complete_recovery_pair(setup, monkeypatch, missing):
    store, backend, _ = setup
    token = store.manifest()['watchdog_token']
    pair = dict(timer=dict(LoadState='loaded', Description=token, Transient='yes',
                           Triggers=backend.timer + '.service'),
                service=dict(LoadState='loaded', Description=token, Transient='yes',
                    ExecStart='{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -I '
                    + str(store.path / 'helper.py') + ' recover ' + str(store.path)
                    + ' ; ignore_errors=no ; }'))
    pair[missing] = None
    monkeypatch.setattr(backend, 'watchdog', lambda: pair)
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('Must reject before is-active'))
    with pytest.raises(RuntimeError, match='Incomplete recovery unit pair'):
        m.Systemd.armed(backend)


def test_terminal_disarm_accepts_absent_owned_pair(setup, monkeypatch):
    _, backend, _ = setup
    from types import SimpleNamespace
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=3))
    assert not m.Systemd.armed(backend, pair_required=False)
