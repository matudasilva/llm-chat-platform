"""No host changes: bytecode/seal regression with temp files and archived bytes."""
import ast
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import pytest

HERE = Path(__file__).parent
SCRIPT = HERE / 'restore-local.sh'
BODY = SCRIPT.read_text().split("<<'RECOVER'\n", 1)[1].rsplit('\nRECOVER', 1)[0]


def function():
    tree = ast.parse(BODY)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'quarantine_import_cache')
    scope = dict(os=os, stat=stat, hashlib=hashlib)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SCRIPT), 'exec'), scope)
    return scope['quarantine_import_cache']


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / '261110205521'
    cache = directory / '__pycache__'
    cache.mkdir(parents=True, mode=0o755)
    with tarfile.open(HERE / 'seal-failure-journal.tar') as archive:
        raw = archive.extractfile('261110205521/__pycache__/helper.cpython-312.pyc').read()
    (cache / 'helper.cpython-312.pyc').write_bytes(raw)
    (cache / 'helper.cpython-312.pyc').chmod(0o600)
    # Only ownership is simulated; path/type/mode/bytes/unlink/fsync are real temp I/O.
    lstat, fstat = Path.lstat, os.fstat
    def root_owned(st):
        values = list(st)
        values[4] = 0
        return os.stat_result(values)
    monkeypatch.setattr(Path, 'lstat', lambda self: root_owned(lstat(self)))
    monkeypatch.setattr(os, 'fstat', lambda fd: root_owned(fstat(fd)))
    return directory


def test_known_artifact_preserved_outside_sealed_state(state):
    function()(state)
    assert not (state / '__pycache__').exists()
    archived = state.parent / 'quarantine-261110205521-pycache/helper.cpython-312.pyc'
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == 'a1deceaabf6531186405c275b61994e78c221d62b66ee7b3f5f5810237d2dc15'
    function()(state)
    assert archived.exists()


def test_extra_cache_content_preserved_and_rejected(state):
    extra = state / '__pycache__/other'
    extra.write_bytes(b'foreign')
    with pytest.raises(RuntimeError, match='Unexpected cache contents'):
        function()(state)
    assert extra.read_bytes() == b'foreign'


def test_changed_cache_bytes_preserved_and_rejected(state):
    artifact = state / '__pycache__/helper.cpython-312.pyc'
    artifact.write_bytes(b'foreign')
    with pytest.raises(RuntimeError, match='Unknown cache bytes'):
        function()(state)
    assert artifact.read_bytes() == b'foreign'


def test_cache_symlink_preserved_and_rejected(state):
    cache = state / '__pycache__'
    moved = state.parent / 'other'
    cache.rename(moved)
    cache.symlink_to(moved, target_is_directory=True)
    with pytest.raises(RuntimeError, match='directory metadata'):
        function()(state)
    assert cache.is_symlink()


def test_unknown_file_mode_preserved_and_rejected(state):
    artifact = state / '__pycache__/helper.cpython-312.pyc'
    artifact.chmod(0o666)
    with pytest.raises(RuntimeError, match='file metadata'):
        function()(state)
    assert artifact.exists()


def test_collision_preserves_both_directories(state):
    archive = state.parent / 'quarantine-261110205521-pycache'
    archive.mkdir()
    with pytest.raises(RuntimeError, match='collision'):
        function()(state)
    assert archive.exists() and (state / '__pycache__').exists()


def test_interruption_after_rename_can_resume(state, monkeypatch):
    fsync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('fsync')))
    with pytest.raises(OSError):
        function()(state)
    assert not (state / '__pycache__').exists()
    monkeypatch.setattr(os, 'fsync', fsync)
    function()(state)


def test_no_artifact_no_quarantine_created(tmp_path):
    function()(tmp_path)
    assert not (tmp_path.parent / 'quarantine-261110205521-pycache').exists()


@pytest.mark.parametrize('prevent', [False, True])
def test_actual_import_reproduces_and_prevents_cache(tmp_path, prevent):
    target = tmp_path / 'helper.py'
    shutil.copyfile(HERE.parent / 'admin_recovery.py', target)
    script = ('import importlib.util,sys; '
              + ('sys.dont_write_bytecode=True; ' if prevent else '')
              + 's=importlib.util.spec_from_file_location("sealed",sys.argv[1]); '
              + 'm=importlib.util.module_from_spec(s); s.loader.exec_module(m)')
    flags = ['-I', '-B'] if prevent else ['-I']
    subprocess.run(['/usr/bin/python3', *flags, '-c', script, str(target)], check=True,
                   env={'PATH': '/usr/bin:/bin'})
    assert (tmp_path / '__pycache__').exists() is not prevent


def test_bytecode_disabled_before_helper_import_and_seal_guard_unchanged():
    assert 'python3 -I -B -' in SCRIPT.read_text()
    assert BODY.index('sys.dont_write_bytecode = True') < BODY.index('spec.loader.exec_module(m)')
    assert BODY.index('quarantine_import_cache(state)\nfinally:') < BODY.index('m.sealed(state)')
    assert "store, backend = m.sealed(state)" in BODY
