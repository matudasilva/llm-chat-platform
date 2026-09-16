"""The honesty sweep (AC22 in origin), and proof it can still catch a real
violation.

A check that can never fail proves nothing (the same lesson AC28's "the
harness could silently disable the feature" and AC13's "a leaking dependency
must be catchable" tests exist for). `test_the_sweep_can_still_catch_a_real_violation`
is that proof here: every exclusion this script adds is validated against
genuine violation text before it is trusted against the real corpus.

**Why the default mode scans the versioned repository, not a delta.** The
sweep was ORQ-37 branch tooling: it diffed against `merge-base origin/main
HEAD` and additionally read the ORQ's own gitignored directory. Once ORQ-37
was promoted, that base *is* HEAD on `main`, so both git sources went empty,
and the ORQ directory is absent from any checkout -- the sweep scanned zero
characters and printed `clean`. The contract it enforces did not expire with
the ORQ: `ebm25_enabled` ships on `main`, ADR-013 is Accepted, and E-BM25
remains unvalidated, which is precisely the condition that makes the
constraint necessary. So the contract stayed and the wiring was replaced.
`test_the_real_sweep_scans_the_repository_and_is_clean` is what makes the
vacuous result impossible to reach again.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "app/scripts/check_honesty_sweep.py"

spec = importlib.util.spec_from_file_location("check_honesty_sweep", SCRIPT)
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)


# Assembled, never written as one literal. Now that the default mode scans
# every tracked file, this file is part of its own corpus: a fixture spelling
# the marker next to a forbidden word would be a finding in the real sweep.
# The same reason the Guardrails tests assemble their secret literals.
_E = "E-" + "BM25"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Honesty Sweep Test")
    return repo


def _write(repo: Path, relative: str, text: str) -> Path:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _commit(repo: Path, message: str = "commit") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _run(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


def _reported(stdout: str) -> tuple[str, int, int]:
    """Parse `mode=..., N files, M chars scanned` out of the summary line."""
    match = re.search(r"mode=(\S+?), (\d+) files, (\d+) chars", stdout)
    assert match, f"the summary line must state mode, files and chars: {stdout!r}"
    return match.group(1), int(match.group(2)), int(match.group(3))


def test_script_exists() -> None:
    assert SCRIPT.exists()


def test_the_real_sweep_scans_the_repository_and_is_clean() -> None:
    """The evidence command for the E-BM25 honesty constraint, run as a test so
    CI enforces it -- and enforces that it actually read something.

    Asserting only `returncode == 0` is what let this pass while scanning
    nothing: on `main` the old delta base resolved to HEAD itself, so `git
    diff` and `git log` were both empty and the ORQ directory was absent. The
    file and character counts are the assertion that matters.
    """
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr

    mode, files, chars = _reported(result.stdout)
    assert mode == "tracked"

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert files == len([line for line in tracked if line.strip()])
    assert chars > 100_000, "the repository cannot plausibly hold this little text"


def test_the_default_scan_does_not_collapse_when_head_has_no_delta() -> None:
    """The exact shape of the original defect, stated as an enduring contract.

    `main` is the case where a delta against the branch point is empty by
    construction, and it is also where CI runs this. A default mode that
    depends on a delta reports `clean` there while checking nothing.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    base = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout.strip()

    _, files, chars = _reported(_run().stdout)
    assert files > 0 and chars > 0

    if base == head:
        # Currently true on `main`, and the whole point: the old default would
        # have scanned nothing here.
        empty_delta = _run("--base", head)
        assert _reported(empty_delta.stdout)[2] == 0


def test_the_sweep_no_longer_depends_on_the_orq_37_directory() -> None:
    """`.framework/orqs/` is gitignored under `artifact_policy: hybrid`, so an
    ORQ directory is absent from every clone and every CI checkout. A default
    scan whose coverage depends on it is coverage nobody else ever gets."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "ORQ-37-rag-in-production" not in source
    assert ".framework/orqs" not in source
    assert not hasattr(_module, "ORQ_DIR")


def test_the_default_scan_reads_real_versioned_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tracked files are scanned; untracked working-tree files are not.

    A finding in a file nobody committed cannot be in any artifact this
    repository publishes, and no push can remove it from one.
    """
    repo = _repo(tmp_path)
    _write(repo, "docs/note.md", f"{_E} is being rolled out behind a flag.\n")
    _commit(repo)
    _write(repo, "scratch.md", f"Testing has valid" + f"ated {_E} completely.\n")

    monkeypatch.setattr(_module, "REPO_ROOT", repo)

    tracked = _module._tracked_files()
    assert [p.name for p in tracked] == ["note.md"]
    assert _module.main([]) == 0


def test_the_tracked_listing_refuses_to_swallow_a_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the listing is `check=True`.

    Without it a failing `git` yields whatever it wrote before dying. The
    empty-scan guard catches a wholly empty result; only `check=True` catches
    a truncated one, which scans a prefix of the repository with a healthy
    character count and reports clean.
    """
    monkeypatch.setattr(_module, "REPO_ROOT", tmp_path)  # not a repository

    with pytest.raises(subprocess.CalledProcessError):
        _module._tracked_files()


def test_the_tracked_listing_survives_a_filename_containing_a_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the listing is NUL-separated.

    Split on newlines, `we\\nird.md` becomes two paths that each read as a
    missing file. The real file is never scanned and the character count still
    looks healthy, so the miss reports clean.
    """
    repo = _repo(tmp_path)
    weird = _write(repo, "we\nird.md", f"{_E} sits behind a flag.\n")
    _commit(repo)

    monkeypatch.setattr(_module, "REPO_ROOT", repo)

    assert _module._tracked_files() == [weird]
    assert _module.main([]) == 0


def test_explicit_base_still_scans_a_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Delta analysis stays available as an explicit mode: it is the right tool
    on a feature branch, where the question is what *this branch* added."""
    repo = _repo(tmp_path)
    _write(repo, "docs/note.md", f"{_E} sits behind a flag.\n")
    base = _commit(repo)
    _write(repo, "docs/note.md", f"{_E} sits behind a flag.\nResults pro" + f"ven for {_E}.\n")
    _commit(repo)

    monkeypatch.setattr(_module, "REPO_ROOT", repo)

    assert _module.main(["--base", base]) == 1
    captured = capsys.readouterr().out
    assert "mode=delta" in captured
    assert "proves" in captured or "proven" in captured


def test_an_empty_scan_is_an_error_not_a_clean_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure this mode is most exposed to is the quiet one.

    Zero files scanned and zero findings is indistinguishable, in the exit
    code, from a repository that is genuinely clean -- which is exactly how
    the original defect stayed invisible in green CI for the whole promotion.
    """
    repo = _repo(tmp_path)

    monkeypatch.setattr(_module, "REPO_ROOT", repo)

    assert _module.main([]) == 1
    assert "scanned nothing" in capsys.readouterr().out


def test_the_roadmap_adjacency_was_fixed_in_content_not_by_relaxing_the_detector() -> None:
    """`roadmap.md` tripped the sweep because the filename `validation.md`
    ended 20 characters before an unrelated bullet's `E-BM25` -- an adjacency
    artifact, not a claim about E-BM25. It was resolved by rewriting that
    sentence, and this pins that the detector was *not* loosened to accommodate
    it: the same shape, synthesised, must still be flagged.
    """
    roadmap = (REPO_ROOT / ".framework/constitution/roadmap.md").read_text(encoding="utf-8")
    assert _module._findings(roadmap, "roadmap") == []

    same_shape = "Full evidence: `valida" + f"tion.md`.\n- ORQ-37's `{_E}` work is an integration"
    assert _module._findings(same_shape, "synthetic") != [], (
        "the detector stopped catching the shape; the fix relaxed detection "
        "instead of changing the document"
    )


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


# `test_orq_directory_scan_covers_gitignored_artifacts` lived here until the
# sweep was generalised. It asserted that the scan read
# `.framework/orqs/ORQ-37-rag-in-production/`, and it was already skipped in
# CI, because `.framework/orqs/` is gitignored under `artifact_policy: hybrid`
# and so is absent from every checkout. That source is gone: coverage that only
# materialises on the one machine holding the artifacts is not coverage, and
# the ORQ it was named after is closed. What endures is the constraint on the
# versioned repository, covered by
# `test_the_real_sweep_scans_the_repository_and_is_clean` above.
