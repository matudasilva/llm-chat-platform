"""Base resolution for the Guardrails scan.

This logic used to live inline in `.github/workflows/guardrails.yml`, where it
was untestable -- the only way to observe it was to watch real CI runs, which
is how two separate defects survived unnoticed:

- On a **new branch** `github.event.before` is all-zeros, and the workflow's
  only fallback was the empty tree. The scan then diffed against nothing and
  treated all 378 files as added, so every new branch went red on pre-existing
  debt.
- On a **force-push** `before` is non-zero but points at the pre-rebase commit,
  which is orphaned by the push and therefore never fetched. `git diff` died
  with exit 128 and the scan checked *nothing* while reporting red -- which
  looks exactly like a real finding.

Every test here builds a real git repository, because both defects are about
what git can and cannot resolve. A mocked `subprocess` would have happily
confirmed the broken behaviour.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.scripts.guardrails_base import EMPTY_TREE, ZERO_SHA, resolve_base

DEFAULT_BRANCH = "main"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An `origin`/clone pair, so `origin/main` is a real remote-tracking ref."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", DEFAULT_BRANCH)
    _git(upstream, "config", "user.email", "t@example.com")
    _git(upstream, "config", "user.name", "t")
    (upstream / "a.txt").write_text("one\n")
    _git(upstream, "add", "a.txt")
    _git(upstream, "commit", "-qm", "first")

    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(upstream), str(clone))
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    return clone


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


# --- 1. push to an existing branch: unchanged semantics ----------------------


def test_a_present_previous_commit_is_used_as_is(repo: Path) -> None:
    """The normal-push path must keep behaving exactly as before."""
    before = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "b.txt", "two\n")

    assert resolve_base(before=before, head=head, default_branch=DEFAULT_BRANCH, repo=repo) == before


# --- 2. branch creation ------------------------------------------------------


def test_a_zero_sha_falls_back_to_the_merge_base(repo: Path) -> None:
    """Branch creation. The old code used the empty tree here, which is what
    made the scan cover the whole repository."""
    base_point = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _commit(repo, "b.txt", "two\n")

    resolved = resolve_base(
        before=ZERO_SHA, head=head, default_branch=DEFAULT_BRANCH, repo=repo
    )

    assert resolved == base_point
    assert resolved != EMPTY_TREE


# --- 3. force-push with an orphaned `before` ---------------------------------


def test_an_orphaned_before_falls_back_instead_of_failing(repo: Path) -> None:
    """The force-push case that killed the scan with exit 128.

    The commit is made genuinely unreachable and then expired from the object
    store, so this reproduces a fresh checkout rather than asserting against a
    commit that merely looks orphaned while still being present.
    """
    base_point = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    orphan = _commit(repo, "b.txt", "two\n")

    _git(repo, "reset", "-q", "--hard", base_point)
    head = _commit(repo, "b.txt", "two rewritten\n")
    _git(repo, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all")
    _git(repo, "gc", "-q", "--prune=now")

    # Precondition: the object really is gone, so `git diff` against it fails.
    assert subprocess.run(
        ["git", "cat-file", "-e", f"{orphan}^{{commit}}"], cwd=repo, capture_output=True
    ).returncode != 0, "the orphan survived; this test would prove nothing"

    resolved = resolve_base(
        before=orphan, head=head, default_branch=DEFAULT_BRANCH, repo=repo
    )

    assert resolved == base_point


# --- 4. a non-commit object is not a valid base ------------------------------


def test_a_non_commit_object_is_not_accepted(repo: Path) -> None:
    """`git cat-file -e <sha>` succeeds for *any* object type, so a bare
    existence check would accept a blob and hand `git diff` something it
    cannot use as a base."""
    base_point = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _commit(repo, "b.txt", "two\n")
    blob = _git(repo, "rev-parse", "HEAD:b.txt")

    resolved = resolve_base(
        before=blob, head=head, default_branch=DEFAULT_BRANCH, repo=repo
    )

    assert resolved == base_point, "a blob was accepted as a commit base"


# --- 5. extreme fallback: no base exists at all ------------------------------


def test_the_empty_tree_is_used_only_when_no_base_exists(tmp_path: Path) -> None:
    """A repository with no `origin/<default>` at all -- e.g. the default
    branch's own first commit. Scanning everything is correct here, and only
    here."""
    solo = tmp_path / "solo"
    solo.mkdir()
    _git(solo, "init", "-q", "-b", DEFAULT_BRANCH)
    _git(solo, "config", "user.email", "t@example.com")
    _git(solo, "config", "user.name", "t")
    head = _commit(solo, "a.txt", "one\n")

    resolved = resolve_base(
        before=ZERO_SHA, head=head, default_branch=DEFAULT_BRANCH, repo=solo
    )

    assert resolved == EMPTY_TREE


# --- 6. the resolved merge-base really is an ancestor ------------------------


def test_the_resolved_merge_base_is_an_ancestor_of_head(repo: Path) -> None:
    """Guards against returning a plausible-looking sha that `git diff` would
    interpret as an unrelated tree."""
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "b.txt", "two\n")
    head = _commit(repo, "c.txt", "three\n")

    resolved = resolve_base(
        before=ZERO_SHA, head=head, default_branch=DEFAULT_BRANCH, repo=repo
    )

    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", resolved, head], cwd=repo, capture_output=True
    ).returncode == 0


# --- the default branch is a parameter, not a constant -----------------------


def test_the_default_branch_is_honoured(tmp_path: Path) -> None:
    """The workflow passes `github.event.repository.default_branch`. A
    hardcoded `main` would silently fall through to the empty tree on any repo
    whose default branch is named otherwise -- reintroducing the whole-repo
    scan without a word in the log.
    """
    upstream = tmp_path / "up"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "trunk")
    _git(upstream, "config", "user.email", "t@example.com")
    _git(upstream, "config", "user.name", "t")
    (upstream / "a.txt").write_text("one\n")
    _git(upstream, "add", "a.txt")
    _git(upstream, "commit", "-qm", "first")

    clone = tmp_path / "cl"
    _git(tmp_path, "clone", "-q", str(upstream), str(clone))
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    base_point = _git(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "-q", "-b", "feature")
    head = _commit(clone, "b.txt", "two\n")

    assert resolve_base(
        before=ZERO_SHA, head=head, default_branch="trunk", repo=clone
    ) == base_point


# --- the CLI the workflow actually calls -------------------------------------


def test_cli_prints_only_the_resolved_base(repo: Path) -> None:
    """The workflow captures stdout, so the base must be the sole thing on it;
    the human-readable line belongs on stderr."""
    before = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "b.txt", "two\n")

    # cwd is the temp repo, because the CLI resolves git relative to the
    # working directory exactly as the workflow does. PYTHONPATH therefore has
    # to point back at the project for the module to be importable.
    project_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(project_root)}
    result = subprocess.run(
        [
            sys.executable, "-m", "app.scripts.guardrails_base",
            "--before", before, "--head", head, "--default-branch", DEFAULT_BRANCH,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert result.stdout.strip() == before
    assert head in result.stderr, "the resolved base/head were not reported"
