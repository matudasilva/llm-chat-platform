from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.scripts import guardrails_scan
from app.scripts.guardrails_scan import main, scan_file


def test_scan_file_flags_sensitive_local_paths(tmp_path: Path) -> None:
    target = tmp_path / "evidence.md"
    target.write_text("Trace:\n/home/alice/project/app/main.py:12: warning\n", encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "local-path"
    assert findings[0].line == 2


def test_scan_file_ignores_placeholders_but_flags_real_secret(tmp_path: Path) -> None:
    target = tmp_path / "secrets.md"
    token = "sk-" + "1234567890ABCDEFGHIJKLMNOP"
    target.write_text(
        f"export OPENAI_API_KEY=\"***\"\nexport OPENAI_API_KEY=\"{token}\"\n",
        encoding="utf-8",
    )

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-token"
    assert findings[0].line == 2


def test_scan_file_ignores_variable_references(tmp_path: Path) -> None:
    target = tmp_path / "provider_factory.py"
    target.write_text("api_key=cfg.openai_api_key\n", encoding="utf-8")

    findings = scan_file(target)

    assert findings == []


# --- `secret-assignment`: an unquoted call result is not an embedded secret ---
#
# The rule matched `token = _set_tenant("acme")` by capturing the *identifier*
# `_set_tenant` as the secret value. The only escape hatch was for unquoted
# values containing a dot (`cfg.openai_api_key`), which a plain call does not
# have. That produced eight findings across two tenant test files and turned
# every new-branch Guardrails run red on debt nobody had introduced.
#
# Relaxing a security rule is only safe if the other direction is pinned too,
# so these tests assert both what must stop firing and what must keep firing.


def test_call_results_are_not_flagged_as_secret_assignments(tmp_path: Path) -> None:
    """The exact shapes behind the eight real findings."""
    target = tmp_path / "test_tenant.py"
    target.write_text(
        'token = _set_tenant("acme")\n'
        'token = _make_bearer({"tenant_id": "beta-corp", "sub": "user1"})\n'
        "password = build_password()\n"
        "api_key = factory ()\n",  # whitespace before the call
        encoding="utf-8",
    )

    assert scan_file(target) == []


def test_quoted_literal_secrets_are_still_flagged(tmp_path: Path) -> None:
    """The escape must not extend to quoted values -- those are real literals."""
    target = tmp_path / "config.py"
    # Assembled rather than written inline, so this file does not itself trip
    # the rule it is testing -- the same reason the `sk-` literal above is
    # split in two.
    literal = "aB3dEf9" + "hIjKlMnOp"
    target.write_text(f'token = "{literal}"\n', encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_quoted_dotted_literals_are_still_flagged(tmp_path: Path) -> None:
    """The attribute-access escape must stay scoped to *unquoted* values.

    A quoted literal containing dots is a very common real secret shape -- a
    JWT is three dotted segments. Dropping the quote guard would exempt it
    along with `cfg.openai_api_key`, which is why the guard is not redundant
    with the call check below it.
    """
    target = tmp_path / "config.py"
    literal = "aB3dEf9" + ".hIjKlMnOp"
    target.write_text(f'token = "{literal}"\n', encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_unquoted_bare_identifiers_are_still_flagged(tmp_path: Path) -> None:
    """Pins the boundary of the relaxation: only *calls* are exempt, not every
    unquoted value. Widening the escape to every unquoted value would silently
    stop flagging a hardcoded bare value assigned to `password`."""
    target = tmp_path / "config.py"
    bare = "hunter2" + "hunter2"
    target.write_text(f"password = {bare}\n", encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_a_real_key_inside_a_call_is_still_caught(tmp_path: Path) -> None:
    """The call escape applies to `secret-assignment` only. A genuine key
    passed as a call argument must still be caught by `secret-token`."""
    target = tmp_path / "config.py"
    key = "sk-" + "1234567890ABCDEFGHIJKLMNOP"
    target.write_text(f'token = decrypt("{key}")\n', encoding="utf-8")

    findings = scan_file(target)

    assert [f.rule for f in findings] == ["secret-token"]


def test_the_two_real_tenant_test_files_are_clean(tmp_path: Path) -> None:
    """The decisive regression: the eight findings reported by CI are gone.

    Scans the shipped files, not a reconstruction of them, so a future edit
    that reintroduces the shape fails here.
    """
    repo_root = guardrails_scan.REPO_ROOT
    targets = [
        repo_root / "tests/api/test_chat_tenant.py",
        repo_root / "tests/http/middleware/test_tenant_middleware.py",
    ]

    for target in targets:
        assert target.is_file(), target
        assert scan_file(target) == [], target


def test_main_without_args_scans_default_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardrails_scan, "default_scan_paths", lambda: [])

    assert main([]) == 0


# --- `--all-tracked`: the full-repository mode ------------------------------
#
# The automated coverage was delta-only, and a delta can only ever see what
# changed *after* the delta existed: a file that predates the workflow, or that
# arrived in a squash-merge, is scanned once and then never again. The broad
# coverage that used to exist was an accident -- the empty-tree fallback on new
# branches -- and correcting that fallback removed it.
#
# Git's index is the source of truth here, not a path allowlist: what is
# versioned is what reaches CI. These tests build real repositories, because the
# boundary with git is precisely where this mode can be wrong while looking
# right.

# Assembled rather than written inline, for the same reason as the literals
# above: this file must not trip the rule it seeds.
_SEEDED_SECRET = "aB3dEf9" + "hIjKlMnOp"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Guardrails Test")
    return repo


def _write(repo: Path, relative: str, text: str) -> Path:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _seed(repo: Path, relative: str) -> Path:
    """A file carrying exactly one `secret-assignment` finding."""
    return _write(repo, relative, f'token = "{_SEEDED_SECRET}"\n')


def _commit(repo: Path, message: str = "commit") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_all_tracked_scans_only_versioned_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index is the contract. A working tree holds build output, caches and
    scratch files that were deliberately never committed; scanning those would
    report findings CI can never see and cannot act on."""
    repo = _repo(tmp_path)
    _write(repo, "tracked.py", "value = 1\n")
    _commit(repo)
    _write(repo, "untracked.py", "value = 2\n")

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert guardrails_scan._git_tracked_files() == [repo / "tracked.py"]


def test_all_tracked_includes_tracked_files_outside_default_scan_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hole, stated in the positive.

    `default_scan_paths()` walks a fixed allowlist -- `app`, `docs`, `scripts`,
    `tests`, `.github` and three root files -- which leaves `experiments/`,
    `.framework/` and most root files uncovered. Both modes are asked about the
    same root here, so the difference is the gap itself and not two setups.
    """
    repo = _repo(tmp_path)
    outside = _seed(repo, "experiments/evaluation/harness.py")
    inside = _write(repo, "app/main.py", "value = 1\n")
    _commit(repo)

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    tracked = guardrails_scan._git_tracked_files()
    defaults = guardrails_scan.default_scan_paths()

    assert outside in tracked
    assert outside not in defaults, "the allowlist would already cover it; the test proves nothing"
    assert inside in tracked and inside in defaults

    assert main(["--all-tracked"]) == 1


def test_all_tracked_ignores_untracked_working_tree_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finding in a file nobody committed must not turn the default branch
    red: it is not in the repository and no push can remove it from one."""
    repo = _repo(tmp_path)
    _write(repo, "tracked.py", "value = 1\n")
    _commit(repo)
    _seed(repo, "scratch.py")

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert main(["--all-tracked"]) == 0
    assert "1 files checked" in capsys.readouterr().out


def test_changed_mode_does_not_use_the_tracked_file_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The delta scan is the fast, attributable feedback and this change must
    leave it alone. If `--all-tracked` leaked into it, every PR would be scanned
    whole and the two scopes would be indistinguishable in the logs."""
    repo = _repo(tmp_path)
    _write(repo, "old.py", "value = 1\n")
    base = _commit(repo, "base")
    _seed(repo, "new.py")
    head = _commit(repo, "head")

    def _refuse() -> list[Path]:
        raise AssertionError("changed mode must not consult the tracked-file list")

    monkeypatch.setattr(guardrails_scan, "_git_tracked_files", _refuse)
    monkeypatch.chdir(repo)

    assert main(["--changed-from", base, "--changed-to", head]) == 1
    assert "mode=changed" in capsys.readouterr().err


def test_all_tracked_returns_nonzero_on_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The mode is blocking. A full scan that reports and exits 0 is a report,
    not a guardrail."""
    repo = _repo(tmp_path)
    _seed(repo, "app/config.py")
    _commit(repo)

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert main(["--all-tracked"]) == 1
    captured = capsys.readouterr()
    assert "mode=all-tracked" in captured.err
    assert "secret-assignment" in captured.err


def test_all_tracked_returns_zero_on_a_clean_tracked_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "app/main.py", "value = 1\n")
    _write(repo, "experiments/harness.py", "value = 2\n")
    _commit(repo)

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert main(["--all-tracked"]) == 0
    assert "mode=all-tracked, 2 files checked" in capsys.readouterr().out


def test_all_tracked_fails_loudly_when_no_files_are_tracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The dangerous failure of this mode is the quiet one.

    An empty list -- a bad cwd, a broken checkout, a `git` that resolved some
    other repository -- scans nothing and prints `0 files checked` in green. It
    would read exactly like full coverage while providing none, so the empty
    list is an error and never a pass.
    """
    repo = _repo(tmp_path)
    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert main(["--all-tracked"]) == 1
    assert "no tracked files" in capsys.readouterr().err


def test_all_tracked_refuses_to_swallow_a_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the listing is `check=True`.

    Without it a failing `git` yields whatever it managed to write before
    dying -- an empty list, or worse a truncated one, which scans a prefix of
    the repository and prints green. The zero-file guard catches the empty
    case; only `check=True` catches the partial one.
    """
    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", tmp_path)  # not a repository

    with pytest.raises(subprocess.CalledProcessError):
        guardrails_scan._git_tracked_files()


@pytest.mark.parametrize(
    "argv",
    [
        ["--all-tracked", "--changed-from", "HEAD~1", "--changed-to", "HEAD"],
        ["--all-tracked", "some_file.py"],
    ],
    ids=["with-changed-range", "with-explicit-paths"],
)
def test_incompatible_mode_combinations_are_rejected(argv: list[str]) -> None:
    """Two scopes in one invocation means one of them is silently discarded, and
    the log line would name only the winner."""
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_the_workflow_runs_the_full_scan_on_default_branch_pushes_only() -> None:
    """The failure mode this change is most exposed to is the silent one.

    A GitHub Actions `if` that evaluates false raises nothing: the step simply
    does not appear, and the job stays green while the gap it was added to close
    is still open. Nothing else here can observe that, so the wiring is pinned
    as text -- deliberately not via PyYAML, which is not a declared dependency.
    """
    workflow = (
        guardrails_scan.REPO_ROOT / ".github/workflows/guardrails.yml"
    ).read_text(encoding="utf-8")
    condition = " ".join(workflow.split())

    assert "--all-tracked" in condition, "the full scan is not wired into CI at all"
    assert (
        "github.event_name == 'push' "
        "&& github.ref_name == github.event.repository.default_branch" in condition
    )
    # The delta scan is not replaced by the full one; both must be present.
    assert "--changed-from" in condition and "--changed-to" in condition


def test_all_tracked_survives_a_filename_containing_a_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the listing is NUL-separated.

    Split on newlines, `we\\nird.py` becomes two paths that each read as a
    missing file, so the count is inflated and the real file is never scanned --
    a miss that still prints green.
    """
    repo = _repo(tmp_path)
    weird = _seed(repo, "we\nird.py")
    _commit(repo)

    monkeypatch.setattr(guardrails_scan, "REPO_ROOT", repo)

    assert guardrails_scan._git_tracked_files() == [weird]
    assert main(["--all-tracked"]) == 1
