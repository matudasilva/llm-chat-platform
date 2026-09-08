"""ORQ-37 T21 — the honesty sweep itself (AC22), and proof it can still catch
a real violation.

A check that can never fail proves nothing (the same lesson AC28's "the
harness could silently disable the feature" and AC13's "a leaking dependency
must be catchable" tests exist for). `test_the_sweep_can_still_catch_a_real_violation`
is that proof here: every exclusion this script adds is validated against
genuine violation text before it is trusted against the real corpus.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "app/scripts/check_honesty_sweep.py"

spec = importlib.util.spec_from_file_location("check_honesty_sweep", SCRIPT)
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)


def test_script_exists() -> None:
    assert SCRIPT.exists()


def test_the_real_sweep_is_clean() -> None:
    """The actual evidence command for AC22, run as a test so CI enforces it."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_sweep_can_still_catch_a_real_violation() -> None:
    genuine_violations = [
        "The dashboard confirms E-BM25 works well for our users.",
        "Internal testing has validated E-BM25 across all providers.",
        "Results demonstrated that E-BM25 improves answer quality significantly.",
        "This proves E-BM25 is effective in production.",
        "The rollout established that E-BM25 is the better retrieval strategy.",
    ]
    for text in genuine_violations:
        findings = _module._findings(text, "synthetic")
        assert findings, f"a real violation was not caught: {text!r}"


def test_the_two_spec_declared_exceptions_are_still_excluded() -> None:
    safe = [
        _module.PREMISE,
        "E-BM25 is not validated or confirmed by this rollout.",
        "No artifact produced by this plan may describe E-BM25 as confirmed.",
    ]
    for text in safe:
        findings = _module._findings(text, "synthetic")
        assert findings == [], f"a scoped exception was wrongly flagged: {text!r}\n{findings}"


def test_backtick_enumeration_is_excluded_but_prose_use_is_not() -> None:
    enumerated = "Forbidden near `E-BM25`: `validated`, `confirmed`."
    assert _module._findings(enumerated, "synthetic") == []

    prose = "Forbidden near E-BM25: it has been validated by the team."
    assert _module._findings(prose, "synthetic") != []


def test_forbidden_words_are_matched_as_whole_words_not_substrings() -> None:
    # "confirmatory" must not accidentally match inside an unrelated longer
    # word, and a word that merely CONTAINS a forbidden substring must not
    # trip the check.
    text = "The reconfirmation panel is near E-BM25 in the diagram."
    findings = _module._findings(text, "synthetic")
    assert findings == [], findings


def test_orq_directory_scan_covers_gitignored_artifacts() -> None:
    # spec.md/implementation.md are gitignored and would never appear in a
    # `git diff`-only sweep. This pins that the directory scan actually reads
    # them, which is the whole reason it exists.
    text = _module._orq_directory_text()
    assert "E-BM25" in text
    assert len(text) > 10_000  # spec.md alone is over 1500 lines
