"""ORQ-41 CPU-placement recovery. No workload, provider or database commands.

Live CLI requires a sealed root-owned installation. Tests inject a local backend.
This implements an administrative apply/restore drill, never a benchmark launcher.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid

UNITS = ('user.slice', 'machine.slice', 'system.slice', 'init.scope')
BENCH = 'orq41bench.slice'
UNIT_BODY = b'[Unit]\nDescription=Temporary ORQ-41 benchmark CPU placement\n[Slice]\nAllowedCPUs=0-7\n'
LEASE_SECONDS = 300
HEADER = '# This is a drop-in unit file extension, created via "systemctl set-property"\n# or an equivalent operation. Do not edit.\n'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def fragment(unit, value):
    section = 'Scope' if unit.endswith('.scope') else 'Slice'
    return (HEADER + f'[{section}]\nAllowedCPUs=\nAllowedCPUs={value}\n').encode()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_new(path, data, mode=0o600):
    """Publish only a complete, fsynced record; never overwrite a prior record."""
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path, follow_symlinks=False)
        sync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
        sync_dir(path.parent)


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode), 'Not a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read()
        return data, (s.st_dev, s.st_ino, s.st_uid, stat.S_IMODE(s.st_mode))
    finally:
        os.close(fd)


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def lock(self):
        require(not self.path.is_symlink() and self.path.is_dir(), 'Unsafe state directory')
        global_fd = os.open(self.path.parent / 'maintenance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fd = os.open(self.path / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(global_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)
            os.close(global_fd)

    def baseline(self):
        body = json.loads(read_regular(self.path / 'baseline.json')[0])
        require(body['hash'] == digest(body['data']), 'Corrupt baseline')
        return body['data']['baseline']

    def manifest(self):
        body = json.loads(read_regular(self.path / 'baseline.json')[0])
        require(body['hash'] == digest(body['data']), 'Corrupt manifest')
        require(body['data']['actions'] == action_contract()
                and body['data']['lease_seconds'] == LEASE_SECONDS, 'Manifest contract drift')
        return body['data']

    def records(self):
        previous, result = '0' * 64, []
        files = sorted(self.path.glob('record-*.json'))
        for index, path in enumerate(files):
            require(path.name == f'record-{index:04d}.json', 'Journal gap/reorder')
            row = json.loads(read_regular(path)[0])
            body = {k: v for k, v in row.items() if k != 'hash'}
            require(set(row) == {'seq', 'previous', 'event', 'value', 'hash'} and row['seq'] == index
                and row['previous'] == previous and row['hash'] == digest(body), 'Corrupt journal')
            result.append(row)
            previous = row['hash']
        return result

    def append(self, event, value=None):
        rows = self.records()
        body = dict(seq=len(rows), previous=rows[-1]['hash'] if rows else '0' * 64,
                    event=event, value=value)
        atomic_new(self.path / f'record-{len(rows):04d}.json', encoded(dict(body, hash=digest(body))))


def action_contract():
    # Every journal index resolves to one immutable target/before/after tuple.
    return [dict(index=i, unit=u, before=None,
                 path=str(Path('/run/systemd/system') / u) if i == 0 else
                      str(Path('/run/systemd/system.control') / (u + '.d') / '50-AllowedCPUs.conf'),
                 after=base64.b64encode(UNIT_BODY if i == 0 else fragment(u, '8-31')).decode(),
                 reset=None if i == 0 else base64.b64encode(fragment(u, '')).decode())
            for i, u in enumerate((BENCH, *UNITS))]


def prepare(path, backend, helper_bytes=None):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), 'Existing maintenance state')
    for other in path.parent.iterdir():
        if other.is_dir() and re.fullmatch('[0-9]{12}', other.name):
            rows = Store(other).records()
            require(validate_log(rows)[2] == 'done', 'Previous maintenance not recovered')
            backend.verify_baseline(Store(other).baseline())
    baseline = backend.snapshot()
    backend.validate_baseline(baseline)
    sync_dir(path.parent.parent)
    sync_dir(path.parent)
    path.mkdir(mode=0o700)
    sync_dir(path.parent)
    helper_bytes = helper_bytes if helper_bytes is not None else Path(__file__).read_bytes()
    atomic_new(path / 'helper.py', helper_bytes, 0o700)
    manifest = dict(baseline=baseline, helper_sha256=hashlib.sha256(helper_bytes).hexdigest(),
                    lease_seconds=LEASE_SECONDS, actions=action_contract(),
                    watchdog_token='orq41-recovery-' + uuid.uuid4().hex)
    atomic_new(path / 'baseline.json', encoded(dict(data=manifest, hash=digest(manifest))))
    store = Store(path)
    with store.lock():
        store.append('PREPARED', digest(baseline))
    return store


def restore_steps(intended):
    steps = []
    for index in reversed(intended):
        if index:
            steps.extend([('RESET', UNITS[index - 1]), ('REMOVE', UNITS[index - 1])])
        else:
            steps.extend([('STOP', BENCH), ('REMOVE', BENCH)])
    return steps + [('FINAL_RELOAD', None)]


def validate_log(rows):
    require(rows and rows[0]['event'] == 'PREPARED', 'Missing prepared journal')
    phase, intended, completed, pending = 'prepared', [], [], None
    for row in rows[1:]:
        event, value = row['event'], row['value']
        if event == 'ARM_INTENT':
            require(phase == 'prepared' and value is None, 'Duplicate arm')
            phase = 'arming'
        elif event == 'ARMED':
            require(phase == 'arming' and value is None, 'Unordered arm')
            phase = 'applying'
        elif event == 'APPLY_INTENT':
            require(phase == 'applying' and pending is None and type(value) is int
                    and value == len(intended) and value < 5, 'Duplicate/unordered apply')
            intended.append(value)
            pending = value
        elif event == 'APPLIED':
            require(phase == 'applying' and pending is not None and type(value) is int
                    and value == pending, 'Unordered application completion')
            pending = None
        elif event == 'OBSERVED':
            require(row['seq'] > 0 and rows[row['seq'] - 1]['event'] in ('APPLIED', 'STEP_DONE')
                    and isinstance(value, dict) and set(value) == {'unit', 'identity'}
                    and value['unit'] in (*UNITS, BENCH), 'Invalid ownership witness')
            previous = rows[row['seq'] - 1]
            expected_unit = ((BENCH, *UNITS)[previous['value']] if previous['event'] == 'APPLIED'
                             else previous['value'][1])
            require(value['unit'] == expected_unit, 'Wrong ownership target')
        elif event == 'RESTORE_BEGIN':
            require(phase in ('prepared', 'arming', 'applying', 'restoring') and value is None,
                    'Invalid restoration')
            phase = 'restoring'
        elif event in ('STEP_INTENT', 'STEP_DONE'):
            require(phase == 'restoring', 'Restoration before intent')
            steps = restore_steps(intended)
            require(len(completed) < len(steps) and value == list(steps[len(completed)]),
                    'Duplicate/unknown/unordered restoration')
            if event == 'STEP_INTENT':
                pending = value
            else:
                require(pending == value, 'Restoration without intent')
                completed.append(value)
                pending = None
        elif event == 'RESTORED':
            require(phase == 'restoring' and len(completed) == len(restore_steps(intended))
                    and pending is None and value is None, 'Premature restoration')
            phase = 'restored'
        elif event == 'DISARM_INTENT':
            require(phase in ('restored', 'disarming') and value is None, 'Premature disarm')
            phase = 'disarming'
        elif event == 'DISARMED':
            require(phase == 'disarming' and value is None, 'Invalid disarm')
            phase = 'done'
        else:
            raise RuntimeError('Unknown journal operation')
    return intended, completed, phase


def apply(store, backend):
    with store.lock():
        store.manifest()
        rows = store.records()
        validate_log(rows)
        require([r['event'] for r in rows] == ['PREPARED'], 'Never replay application')
        baseline = store.baseline()
        require(backend.snapshot() == baseline, 'Baseline drift before application')
        store.append('ARM_INTENT')
        try:
            backend.arm()
            require(backend.armed(), 'Recovery timer not armed')
            store.append('ARMED')
            deadline = time.monotonic() + LEASE_SECONDS - 60
            for index in range(5):
                require(time.monotonic() < deadline and backend.armed(), 'Recovery lease lost')
                store.append('APPLY_INTENT', index)
                backend.apply_one(index)
                backend.verify_one(index)
                store.append('APPLIED', index)
                unit = (BENCH, *UNITS)[index]
                store.append('OBSERVED', dict(unit=unit, identity=backend.identity(unit)))
        except Exception:
            recover_locked(store, backend)
            raise


def recover_locked(store, backend):
    store.manifest()
    rows = store.records()
    intended, completed, phase = validate_log(rows)
    baseline = store.baseline()
    if phase == 'done':
        backend.verify_baseline(baseline)
        require(not backend.armed(pair_required=False), 'Unexpected recovery timer')
        return
    if phase in ('restored', 'disarming'):
        backend.verify_baseline(baseline)
    else:
        backend.ensure_empty()
        backend.validate_recoverable(baseline, intended, rows)
        store.append('RESTORE_BEGIN')
        for operation, unit in restore_steps(intended)[len(completed):]:
            # Re-read before every mutation, including a previously outstanding
            # intent. A completed step is never blindly executed a second time.
            backend.validate_recoverable(baseline, intended, store.records())
            store.append('STEP_INTENT', [operation, unit])
            if operation == 'RESET':
                backend.reset(unit)
            elif operation == 'REMOVE':
                backend.remove_owned(unit)
            elif operation == 'STOP':
                backend.stop_empty()
            else:
                backend.reload()
                backend.verify_baseline(baseline)
            store.append('STEP_DONE', [operation, unit])
            if operation in ('RESET', 'REMOVE'):
                store.append('OBSERVED', dict(unit=unit, identity=backend.identity(unit)))
        store.append('RESTORED')
    store.append('DISARM_INTENT')
    backend.disarm()
    require(not backend.armed(pair_required=False), 'Recovery timer still armed')
    store.append('DISARMED')


def recover(store, backend):
    # The independent service retries on failure (including lock contention).
    with store.lock():
        recover_locked(store, backend)


class Systemd:
    """Fixed allowlist; no shell or arbitrary command arguments from state."""
    def __init__(self, state):
        self.state = Path(state)
        self.timer = 'orq41-cpuset-recovery-' + self.state.name
        self.paths = {u: Path('/run/systemd/system.control') / (u + '.d') / '50-AllowedCPUs.conf' for u in UNITS}
        self.paths[BENCH] = Path('/run/systemd/system') / BENCH

    def command(self, *args):
        result = subprocess.run(args, capture_output=True, timeout=15,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        require(result.returncode == 0, 'Administrative command failed: ' + args[0])
        return result.stdout.decode().strip()

    def props(self, unit):
        names = ('AllowedCPUs', 'StartupAllowedCPUs', 'EffectiveCPUs', 'FragmentPath', 'DropInPaths', 'ActiveState', 'ControlGroup')
        text = self.command('/usr/bin/systemctl', 'show', *('-p' + k for k in names), unit)
        return dict(line.split('=', 1) for line in text.splitlines())

    def file(self, unit):
        path = self.paths[unit]
        for parent in (path.parent, *path.parents):
            if parent.exists() or parent.is_symlink():
                st = parent.lstat()
                require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022, 'Unsafe runtime ancestry')
        if not path.exists() and not path.is_symlink():
            return None
        raw, identity = read_regular(path)
        require(identity[2] == 0 and identity[3] == 0o644, 'Unexpected root file metadata')
        return base64.b64encode(raw).decode()

    def identity(self, unit):
        if self.file(unit) is None:
            return None
        return list(read_regular(self.paths[unit])[1])

    def snapshot(self):
        return dict(units={u: self.props(u) for u in (*UNITS, BENCH)},
                    files={u: self.file(u) for u in (*UNITS, BENCH)},
                    inventory=self.inventory(), watchdog=self.watchdog())

    def inventory(self):
        # Read-only preservation witnesses; never stop/restart these containers.
        names = ('orq41-paid-pg', 'orq41-env-pg', 'orq41-env-redis', 'orq41-env-otel')
        containers = json.loads(self.command('/usr/bin/docker', 'inspect', *names))
        kept = [{k: row[k] for k in ('Id', 'Name', 'RestartCount')} |
                {'status': row['State']['Status'], 'pid': row['State']['Pid'],
                 'started': row['State']['StartedAt']} for row in containers]
        power = {}
        for cpu in (0, 2, 4, 6):
            for name in ('scaling_governor', 'energy_performance_preference'):
                path = Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/{name}')
                power[str(path)] = path.read_text().strip()
        return dict(containers=kept, power=power)

    def validate_baseline(self, before):
        require(all(v is None for v in before['watchdog'].values()), 'Recovery unit collision')
        require(all(value is None for value in before['files'].values()), 'Pre-existing owned path')
        for unit in UNITS:
            p = before['units'][unit]
            require(p['AllowedCPUs'] == p['StartupAllowedCPUs'] == p['DropInPaths'] == ''
                    and p['EffectiveCPUs'] == '0-31', 'Unsupported administrative baseline')
        require(before['units'][BENCH]['DropInPaths'] == ''
                and before['units'][BENCH]['StartupAllowedCPUs'] == ''
                and before['units'][BENCH]['AllowedCPUs'] == ''
                and before['units'][BENCH]['ActiveState'] == 'inactive'
                and before['units'][BENCH]['FragmentPath'] == '', 'Benchmark slice collision')

    def watchdog(self):
        result = {}
        for kind in ('timer', 'service'):
            fields = ('LoadState', 'Description', 'Transient',
                      'Triggers' if kind == 'timer' else 'ExecStart')
            output = self.command('/usr/bin/systemctl', 'show',
                                  *('-p' + k for k in fields), self.timer + '.' + kind)
            props = dict(line.split('=', 1) for line in output.splitlines())
            result[kind] = None if props['LoadState'] == 'not-found' else props
        return result

    def verify_owned_watchdog(self, pair_required=False):
        units = self.watchdog()
        token = Store(self.state).manifest()['watchdog_token']
        for kind, p in units.items():
            if p is None:
                require(not pair_required, 'Incomplete recovery unit pair')
                continue
            require(p['LoadState'] == 'loaded' and p['Description'] == token
                    and p['Transient'] == 'yes', 'Foreign recovery unit: leave untouched')
            if kind == 'timer':
                require(p['Triggers'] == self.timer + '.service', 'Wrong recovery service')
            else:
                prefix = ('{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -I '
                          + str(self.state / 'helper.py') + ' recover ' + str(self.state)
                          + ' ; ignore_errors=no ;')
                require(p['ExecStart'].startswith(prefix) and p['ExecStart'].count('{') == 1,
                        'Wrong recovery executable')
        return units

    def arm(self):
        require(all(v is None for v in self.watchdog().values()), 'Existing recovery unit')
        token = Store(self.state).manifest()['watchdog_token']
        self.command('/usr/bin/systemd-run', '--unit=' + self.timer, '--on-active=300s',
            '--description=' + token, '--timer-property=Description=' + token,
            '--timer-property=AccuracySec=1s', '--property=Restart=on-failure',
            '--property=RestartSec=10s', '--property=StartLimitIntervalSec=0',
            '/usr/bin/python3', '-I', str(self.state / 'helper.py'), 'recover', str(self.state))
        self.verify_owned_watchdog(pair_required=True)

    def armed(self, pair_required=True):
        self.verify_owned_watchdog(pair_required=pair_required)
        r = subprocess.run(['/usr/bin/systemctl', 'is-active', self.timer + '.timer'],
                           capture_output=True, timeout=10,
                           env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        return r.returncode == 0

    def disarm(self):
        units = self.verify_owned_watchdog()
        if units['timer'] is not None:
            self.command('/usr/bin/systemctl', 'stop', self.timer + '.timer')

    def reload(self):
        self.command('/usr/bin/systemctl', 'daemon-reload')

    def apply_one(self, index):
        if index == 0:
            atomic_new(self.paths[BENCH], UNIT_BODY, 0o644)
            self.reload()
            self.command('/usr/bin/systemctl', 'start', BENCH)
        else:
            self.command('/usr/bin/systemctl', 'set-property', '--runtime', UNITS[index - 1], 'AllowedCPUs=8-31')

    def verify_one(self, index):
        unit = BENCH if index == 0 else UNITS[index - 1]
        expected = UNIT_BODY if index == 0 else fragment(unit, '8-31')
        require(self.file(unit) == base64.b64encode(expected).decode(), 'Unrecognized systemd fragment')
        p = self.props(unit)
        require(p['AllowedCPUs'] == p['EffectiveCPUs'] == ('0-7' if index == 0 else '8-31'), 'Effective placement mismatch')

    def ensure_empty(self):
        path = Path('/sys/fs/cgroup') / BENCH / 'cgroup.events'
        if path.exists():
            require('populated 0' in path.read_text().splitlines(), 'NOT DRAINED: no workloads may be killed')

    def validate_recoverable(self, baseline, intended, rows):
        require(self.inventory() == baseline['inventory'], 'Preservation inventory drift')
        # A completed readback binds file identity until the next owned mutation.
        for unit in (BENCH, *UNITS):
            witness = None
            for row in rows:
                if row['event'] == 'OBSERVED' and row['value']['unit'] == unit:
                    witness = row['value']
                elif (row['event'] == 'APPLY_INTENT' and (BENCH, *UNITS)[row['value']] == unit
                      or row['event'] == 'STEP_INTENT' and row['value'][1] == unit):
                    witness = None
            if witness is not None:
                require(self.identity(unit) == witness['identity'], 'Owned file replaced')
        for index, unit in enumerate((BENCH, *UNITS)):
            actual = self.file(unit)
            expected = [None]
            if index in intended:
                expected.append(base64.b64encode(UNIT_BODY if index == 0 else fragment(unit, '8-31')).decode())
                if unit in UNITS and any(r['event'] == 'STEP_INTENT' and r['value'] == ['RESET', unit] for r in rows):
                    expected.append(base64.b64encode(fragment(unit, '')).decode())
            removed = any(r['event'] == 'STEP_DONE' and r['value'] == ['REMOVE', unit] for r in rows)
            if removed:
                expected = [None]
            require(actual in expected, 'Unknown/concurrent runtime fragment; leave untouched')
            if unit == BENCH:
                p = self.props(unit)
                require(p['DropInPaths'] == p['StartupAllowedCPUs'] == ''
                        and p['FragmentPath'] in ('', str(self.paths[BENCH]))
                        and p['AllowedCPUs'] in ('', '0-7'), 'Foreign benchmark configuration')
            if unit in UNITS:
                p = self.props(unit)
                require(p['StartupAllowedCPUs'] == '' and p['AllowedCPUs'] in ('', '8-31')
                    and (index in intended or p['AllowedCPUs'] == ''), 'Unexpected manager state')
                allowed_dropins = ['', str(self.paths[unit])]
                require(p['DropInPaths'] in allowed_dropins, 'Foreign runtime override')

    def reset(self, unit):
        actual = self.file(unit)
        p = self.props(unit)
        if p['AllowedCPUs'] == '' and actual in (None, base64.b64encode(fragment(unit, '')).decode()):
            return
        self.command('/usr/bin/systemctl', 'set-property', '--runtime', unit, 'AllowedCPUs=')
        require(self.file(unit) == base64.b64encode(fragment(unit, '')).decode(), 'Unexpected rollback fragment')

    def remove_owned(self, unit):
        path = self.paths[unit]
        if not path.exists() and not path.is_symlink():
            return
        expected = UNIT_BODY if unit == BENCH else fragment(unit, '')
        raw, identity = read_regular(path)
        require(raw == expected and identity[2:] == (0, 0o644), 'Refuse foreign file deletion')
        now = path.lstat()
        require((now.st_dev, now.st_ino) == identity[:2], 'File replaced during restoration')
        path.unlink()
        sync_dir(path.parent)

    def stop_empty(self):
        self.ensure_empty()
        if self.props(BENCH)['ActiveState'] == 'active':
            self.command('/usr/bin/systemctl', 'stop', BENCH)

    def verify_baseline(self, baseline):
        current = self.snapshot()
        require(current['inventory'] == baseline['inventory'], 'Container/power preservation failed')
        require(current['files'] == baseline['files'], 'Runtime file parity failed')
        for unit in UNITS:
            require(current['units'][unit] == baseline['units'][unit], 'Manager/effective baseline parity failed')
        require(current['units'][BENCH]['ActiveState'] == 'inactive', 'Benchmark slice remains active')


def sealed(path):
    require(os.geteuid() == 0, 'Root installation required')
    path = Path(path)
    require(path.parent == Path('/var/lib/orq41-cpuset') and re.fullmatch('[0-9]{12}', path.name), 'Unknown maintenance path')
    for parent in (Path('/var'), Path('/var/lib'), path.parent, path):
        s = parent.lstat()
        require(stat.S_ISDIR(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022, 'Unsealed state ancestry')
    for entry in path.iterdir():
        st = entry.lstat()
        require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022, 'Unsafe sealed state file')
    data, identity = read_regular(path / 'helper.py')
    require(identity[2] == 0 and not identity[3] & 0o022 and Path(__file__).resolve() == path / 'helper.py', 'Unsealed recovery helper')
    require(hashlib.sha256(data).hexdigest() == Store(path).manifest()['helper_sha256'], 'Recovery helper drift')
    return Store(path), Systemd(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'recover', 'verify'))
    parser.add_argument('state', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        require(os.geteuid() == 0, 'Root required')
        require(args.state.parent == Path('/var/lib/orq41-cpuset')
                and re.fullmatch('[0-9]{12}', args.state.name), 'Unknown maintenance path')
        for parent in (Path('/var'), Path('/var/lib'), args.state.parent):
            st = parent.lstat()
            require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022, 'Unsafe parent')
        prepare(args.state, Systemd(args.state))
        print('PREPARED_NOT_APPLIED')
        sys.exit(0)
    state, backend = sealed(args.state)
    if args.action == 'apply':
        apply(state, backend)
    elif args.action == 'recover':
        recover(state, backend)
    else:
        with state.lock():
            validate_log(state.records())
            backend.verify_baseline(state.baseline())
    print(args.action.upper() + '_PASS')
