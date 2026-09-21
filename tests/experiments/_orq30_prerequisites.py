"""Prerequisite guard for the ORQ-30 authenticated tokenizer runtime.

`load_offline_encoding` fails closed on four conditions, in this order: an
exact Python version, an exact `tiktoken` version, an authenticated asset whose
SHA-256 matches the frozen value, and `TIKTOKEN_CACHE_DIR` pointing at exactly
that cache. Failing closed is correct -- the experiment's token accounting is
only reproducible against one tokenizer -- but a *test* that dies on it reports
a missing runtime as a `TokenizerIntegrityError`, indistinguishable from the
integrity violation that exception exists to signal. Twenty-two tests did
exactly that: 21 as errors and one as a failure, with `replay`'s raising a bare
`KeyError` that named nothing at all.

The runtime is deliberately absent from `app/requirements-dev.txt`. It is an
isolated, hash-pinned runtime declared in
`experiments/long_context_conversational_memory/requirements-tokenizer.lock`,
and the asset it authenticates lives under `.framework/cache/`, which is
gitignored. So its absence is the normal state of a normal checkout, and the
honest report for it is a skip that says which prerequisite is missing -- not a
failure, and not a weakened assertion. Where the runtime exists, every guarded
test runs exactly the assertions it runs today.

The condition is the runtime's own absence, never `CI`: a checkout without the
runtime behaves the same wherever it runs. This mirrors `requires_orq_spec` in
`tests/core/test_adr_012_013.py` and `tests/core/test_memory_envelope.py`.
"""

from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path

import pytest

from experiments.long_context_conversational_memory.tokenization import (
    ASSET_CACHE_KEY,
    TOKENIZER_PACKAGE_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# The one cache path the runtime authenticates. Defined here so all three
# consumers name it once instead of each spelling it out.
TOKENIZER_CACHE_DIR = REPO_ROOT / ".framework/cache/orq-30/tiktoken"

# `tokenization.py:77` compares `platform.python_version()` against this
# literal inline rather than exposing a constant, so it is the one pin this
# module has to restate. `test_the_prerequisite_python_pin_matches_the_runtime`
# in `test_orq30_tokenization.py` fails if the two ever drift -- a stale value
# here would skip a runtime that is actually present, or run against one that
# is not, and either way the skip would be lying.
TOKENIZER_PYTHON_VERSION = "3.13.9"

_LOCK = (
    "experiments/long_context_conversational_memory/requirements-tokenizer.lock"
)


def _display_path(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def tokenizer_runtime_unavailable() -> str | None:
    """Why the ORQ-30 tokenizer runtime cannot be used, or None if it can.

    Checked in the same order `load_offline_encoding` checks them, so the
    reason reported is the first one that implementation would hit.
    """
    running = platform.python_version()
    if running != TOKENIZER_PYTHON_VERSION:
        return (
            f"the ORQ-30 tokenizer runtime pins Python {TOKENIZER_PYTHON_VERSION} "
            f"and this interpreter is {running}; token accounting is only "
            f"reproducible on the pinned runtime"
        )

    try:
        installed = importlib.metadata.version("tiktoken")
    except importlib.metadata.PackageNotFoundError:
        return (
            f"tiktoken is not installed. It is deliberately absent from "
            f"app/requirements-dev.txt: the ORQ-30 tokenizer is an isolated, "
            f"hash-pinned runtime declared in {_LOCK}"
        )
    if installed != TOKENIZER_PACKAGE_VERSION:
        return (
            f"the ORQ-30 tokenizer runtime pins tiktoken "
            f"{TOKENIZER_PACKAGE_VERSION} and {installed} is installed; "
            f"install exactly from {_LOCK}"
        )

    return asset_unavailable()


def asset_unavailable() -> str | None:
    """Why the authenticated tokenizer asset is absent, or None if present."""
    if not (TOKENIZER_CACHE_DIR / ASSET_CACHE_KEY).is_file():
        # Not `relative_to(REPO_ROOT)`: that raises when the cache sits outside
        # the repository, which would turn this explanatory message into a
        # crash -- the exact substitution of a confusing failure for a clear
        # skip that this module exists to prevent.
        return (
            f"the authenticated tokenizer asset is absent from "
            f"{_display_path(TOKENIZER_CACHE_DIR)}, which is gitignored under "
            f".framework/cache/ and so is not part of any checkout"
        )
    return None


_REASON = tokenizer_runtime_unavailable()

requires_orq30_tokenizer = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


# The two ORQ-30 artifacts some tests read without needing the tokenizer
# runtime. Both guards test presence only: an artifact that exists but does not
# match still fails its test, so no mismatch is ever reported as a skip.
ORQ30_MANIFEST = (
    REPO_ROOT
    / ".framework/orqs/ORQ-30-long-context-conversational-memory/experiment-manifest.json"
)

requires_orq30_manifest = pytest.mark.skipif(
    not ORQ30_MANIFEST.is_file(),
    reason=(
        f"{_display_path(ORQ30_MANIFEST)} is absent: `.framework/orqs/` is "
        "intentionally gitignored under `artifact_policy: hybrid`, so it is not "
        "part of any checkout. This assertion runs where the ORQ artifacts exist."
    ),
)

# `validate_asset` needs only `hashlib`, not the pinned Python or `tiktoken`,
# so this checks the asset alone rather than the whole runtime.
_ASSET_REASON = asset_unavailable()

requires_orq30_asset = pytest.mark.skipif(
    _ASSET_REASON is not None, reason=_ASSET_REASON or ""
)
