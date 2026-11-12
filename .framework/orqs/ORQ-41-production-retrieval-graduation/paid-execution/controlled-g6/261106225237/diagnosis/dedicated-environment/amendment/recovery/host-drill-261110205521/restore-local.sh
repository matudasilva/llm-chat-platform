#!/bin/sh
# Operator-local recovery only. Does not apply placement or modify the helper.
# Password stays in the operator terminal. No automatic permission expansion.
set -eu
sudo /usr/bin/python3 -I -B - <<'RECOVER'
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
import fcntl

sys.dont_write_bytecode = True


def quarantine_import_cache(state):
    """Preserve only the exact known bytecode artifact created by our import."""
    cache = state / "__pycache__"
    archive = state.parent / "quarantine-261110205521-pycache"
    expected = "helper.cpython-312.pyc"
    expected_sha = "a1deceaabf6531186405c275b61994e78c221d62b66ee7b3f5f5810237d2dc15"

    def sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def verify(directory):
        st = directory.lstat()
        if not (stat.S_ISDIR(st.st_mode) and st.st_uid == 0
                and stat.S_IMODE(st.st_mode) == 0o755):
            raise RuntimeError("Unknown cache directory metadata: leave untouched")
        if sorted(p.name for p in directory.iterdir()) != [expected]:
            raise RuntimeError("Unexpected cache contents: leave untouched")
        fd = os.open(directory / expected, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            if not (stat.S_ISREG(st.st_mode) and st.st_uid == 0
                    and stat.S_IMODE(st.st_mode) == 0o600):
                raise RuntimeError("Unknown cache file metadata: leave untouched")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                raise RuntimeError("Unknown cache bytes: leave untouched")
        finally:
            os.close(fd)

    present = cache.exists() or cache.is_symlink()
    archived = archive.exists() or archive.is_symlink()
    if present and archived:
        raise RuntimeError("Cache/archive collision: leave both untouched")
    if present:
        verify(cache)
        os.rename(cache, archive)
        # Both directory entries must be durable before proceeding to recovery.
        sync_directory(state)
        sync_directory(state.parent)
    elif archived:
        verify(archive)
        sync_directory(state)
        sync_directory(state.parent)
    # The original sealed() check is not relaxed or bypassed.


state = Path('/var/lib/orq41-cpuset/261110205521')
helper = state / 'helper.py'
assert os.geteuid() == 0
assert not helper.is_symlink()
assert hashlib.sha256(helper.read_bytes()).hexdigest() == '9025f3924dfcc49a6debbe82a835be0bd42e4e3eebeec9fb4f672d512742a2e6'
# Coordinate artifact movement with the original watchdog, before importing.
for parent in (Path('/var'), Path('/var/lib'), state.parent, state):
    st = parent.lstat()
    assert stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022
lock_fds = []
try:
    for lock in (state.parent / 'maintenance.lock', state / 'lock'):
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        lock_fds.append(fd)
        st = os.fstat(fd)
        assert stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022
        fcntl.flock(fd, fcntl.LOCK_EX)
    quarantine_import_cache(state)
finally:
    for fd in reversed(lock_fds):
        os.close(fd)
spec = importlib.util.spec_from_file_location('sealed_recovery', helper)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
store, backend = m.sealed(state)
path = Path('/run/systemd/transient/init.scope.d/50-AllowedCPUs.conf')

def record_once(name, value):
    target = state / name
    if target.exists() or target.is_symlink():
        raw, identity = m.read_regular(target)
        m.require(identity[2:] == (0, 0o600) and raw == m.encoded(value), 'Manual journal conflict')
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        m.sync_dir(state)
    else:
        m.atomic_new(target, m.encoded(value))

with store.lock():
    rows = store.records()
    intended, completed, phase = m.validate_log(rows)
    before = store.baseline()
    m.require(intended == [0, 1, 2, 3, 4], 'Unexpected journal: never replay apply')
    m.require(before['units']['init.scope']['AllowedCPUs'] == ''
              and before['units']['init.scope']['DropInPaths'] == '', 'Unsupported baseline')
    backend.ensure_empty()
    m.require(backend.inventory() == before['inventory'], 'Preservation inventory drift')
    for parent in path.parents:
        s = parent.lstat()
        m.require(stat.S_ISDIR(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022,
                  'Unsafe transient path ancestry')
    intent = dict(operation='restore_only_observed_transient_init_override', path=str(path),
                  before_identity=[28, 70296, 0, 420],
                  before_sha256='9fdc9dcb89a9a2ba32e3c634bbf96019979a60156357b3eb990acc45f6930d67',
                  expected_allowed_cpus='', expected_file_after=None)
    intent_path = state / 'manual-init-intent.json'
    if not intent_path.exists():
        m.require(phase == 'applying' and not completed, 'Unexplained recovery state')
        raw, identity = m.read_regular(path)
        m.require(raw == m.fragment('init.scope', '8-31')
                  and list(identity) == intent['before_identity'], 'Original fragment changed')
    record_once('manual-init-intent.json', intent)
    p = backend.props('init.scope')
    if path.exists() or path.is_symlink():
        m.require(phase == 'applying' and not completed
                  and p['DropInPaths'] == str(path) and p['AllowedCPUs'] in ('', '8-31')
                  and p['StartupAllowedCPUs'] == '', 'Unknown init.scope configuration')
        raw, identity = m.read_regular(path)
        m.require(identity[2:] == (0, 0o644), 'Unexpected fragment metadata')
        if raw == m.fragment('init.scope', '8-31'):
            m.require(list(identity) == intent['before_identity'], 'Original file replaced')
            backend.command('/usr/bin/systemctl', 'set-property', '--runtime', 'init.scope', 'AllowedCPUs=')
            raw, identity = m.read_regular(path)
        m.require(raw == m.fragment('init.scope', '') and identity[2:] == (0, 0o644),
                  'Unexpected reset fragment: leave untouched')
        record_once('manual-init-reset.json', dict(
            identity=list(identity), sha256=hashlib.sha256(raw).hexdigest()))
        now = path.lstat()
        m.require((now.st_dev, now.st_ino) == identity[:2], 'File replaced: do not unlink')
        path.unlink()
    else:
        m.require(p['AllowedCPUs'] == '' and p['DropInPaths'] in ('', str(path)),
                  'Absent fragment but unknown manager state')
    # Repeat fsync/reload after an ambiguous unlink or interrupted previous reload.
    m.sync_dir(path.parent)
    backend.reload()
    m.require(backend.props('init.scope') == before['units']['init.scope'], 'init.scope parity failed')
    record_once('manual-init-restored.json', dict(path=str(path), file_absent=True,
                                                properties=backend.props('init.scope')))
    # Resume only the already reviewed reverse recovery; NEVER replay apply.
    m.recover_locked(store, backend)
    backend.verify_baseline(before)
    m.require(not backend.armed(pair_required=False), 'Recovery timer still active')
print('ORQ41_BASELINE_RESTORED_AND_VERIFIED')
RECOVER
