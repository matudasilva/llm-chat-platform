"""Resolve the base commit the Guardrails scan should diff against.

This lived inline in `.github/workflows/guardrails.yml`, where it could not be
tested and where two defects survived unnoticed because the workflow never
printed what it had resolved:

- **New branch.** `github.event.before` is all-zeros, and the only fallback was
  the empty tree. The scan diffed against nothing, treated every file in the
  repository as added, and went red on pre-existing debt nobody had introduced.
  A check that is red by default trains people to ignore it.
- **Force-push.** `before` is non-zero but names the pre-rebase commit, which
  the push orphans. An orphaned commit is unreachable from any ref, so a fresh
  checkout never fetches it -- `fetch-depth: 0` brings refs, not dangling
  objects -- and `git diff` exited 128. The scan then verified *nothing* while
  reporting failure, which reads exactly like a real finding.

Both are resolved the same way: a base is only usable if it is a commit that
this checkout can actually see. Anything else falls back to the branch point
with the default branch, and the empty tree survives only for the case it was
always right for -- a repository with no base at all.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ZERO_SHA = "0" * 40
# `git hash-object -t tree /dev/null` -- the well-known empty tree. Hardcoded
# so resolving a base never depends on a subprocess that could itself fail.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )


def _is_usable_commit(repo: Path | None, ref: str) -> bool:
    """Whether `ref` names a commit this checkout can resolve.

    `^{commit}` is not decoration: `git cat-file -e <sha>` succeeds for any
    object type, so a bare existence check would accept a blob or a tree and
    hand `git diff` something it cannot use as a base.
    """
    if not ref or ref == ZERO_SHA:
        return False
    return _git(repo, "cat-file", "-e", f"{ref}^{{commit}}").returncode == 0


def resolve_base(
    *, before: str, head: str, default_branch: str, repo: Path | None = None
) -> str:
    """The commit to diff against, in order of preference."""
    # 1. The real previous commit, when it is both non-zero and still present.
    #    Both halves matter -- a force-push leaves `before` non-zero yet gone.
    if _is_usable_commit(repo, before):
        return before

    # 2. Branch creation, or a base this checkout can no longer see: scan what
    #    this branch adds relative to the default branch.
    merge_base = _git(repo, "merge-base", f"origin/{default_branch}", head)
    if merge_base.returncode == 0 and merge_base.stdout.strip():
        return merge_base.stdout.strip()

    # 3. Last resort: no base exists at all (the default branch's own first
    #    commit, say). Scanning everything is correct here, and only here.
    return EMPTY_TREE


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="github.event.before, or the PR base sha")
    parser.add_argument("--head", required=True, help="github.sha")
    parser.add_argument(
        "--default-branch",
        required=True,
        help="github.event.repository.default_branch -- never hardcode it, a "
        "renamed default branch would silently fall through to the empty tree",
    )
    args = parser.parse_args(argv)

    base = resolve_base(
        before=args.before, head=args.head, default_branch=args.default_branch
    )

    # stdout carries the base alone, because the workflow captures it.
    # The human-readable line goes to stderr so the log always records what was
    # compared -- the absence of exactly this is why the whole-repo scan went
    # unnoticed for so long.
    print(f"guardrails: base={base} head={args.head}", file=sys.stderr)
    print(base)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
