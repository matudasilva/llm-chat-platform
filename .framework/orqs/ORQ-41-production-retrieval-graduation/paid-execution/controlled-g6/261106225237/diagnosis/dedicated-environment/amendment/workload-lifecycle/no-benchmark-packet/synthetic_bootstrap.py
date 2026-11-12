"""Load the reviewed lifecycle core from this read-only adapter directory."""
import hashlib
import os
import stat
import sys
import types
from pathlib import Path


CORE_SHA256 = "9d8547bd60265c883ae46a1987776f6138f7c1a62dacb2f07dba26d8fc488545"


def load_lifecycle(core_path=None):
    """Verify then execute the exact bytes read from the adjacent core snapshot."""
    path = Path(core_path) if core_path is not None else Path(__file__).resolve().with_name("core.py")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Pinned lifecycle core is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read()
    finally:
        os.close(fd)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != CORE_SHA256:
        raise ValueError("Pinned lifecycle core hash mismatch")
    name = "_orq41_pinned_lifecycle_core"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    # Execute only the already-read, hash-verified bytes; do not reopen the path.
    code = compile(raw, str(path), "exec", dont_inherit=True)
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
