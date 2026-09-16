from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PATH_RE = re.compile(r"(?<![\w.-])/(?:home|Users)/[^\s'\"`<>\\]+")
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|private[_-]?key)\b"
    r"\s*[:=]\s*(?P<quote>['\"]?)(?P<value>[A-Za-z0-9._/\-+=]{8,})(?P=quote)?"
)

SAFE_PLACEHOLDERS = {
    "***",
    "changeme",
    "example",
    "placeholder",
    "redacted",
    "test",
    "your_api_key_here",
    "your-key-here",
    "your_secret_here",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    column: int
    rule: str
    detail: str


def _is_safe_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'").strip().lower()
    return normalized in SAFE_PLACEHOLDERS


def _is_code_reference(line: str, match: re.Match[str]) -> bool:
    """True when the matched value is code, not an embedded literal.

    `SECRET_ASSIGNMENT_RE` captures whatever follows `token =`, so an
    expression is captured as if it were the secret itself: `_set_tenant` in
    `token = _set_tenant("acme")`. Two unquoted shapes can never be a
    hardcoded secret and are exempt -- attribute access (`cfg.openai_api_key`)
    and a call.

    Quoted values are never exempt: those are literals, which is exactly what
    this rule exists to catch. Nor is a bare unquoted identifier, so a
    hardcoded value assigned to `password` keeps firing.

    This exemption is scoped to `secret-assignment`. A genuine key passed as a
    call argument is still caught by `OPENAI_KEY_RE`/`AWS_KEY_RE`, which match
    anywhere on the line.
    """
    if match.group("quote") != "":
        return False
    if "." in match.group("value"):
        return True
    return line[match.end("value") :].lstrip(" \t").startswith("(")


def scan_line(path: Path, line_no: int, line: str) -> list[Finding]:
    findings: list[Finding] = []
    saw_explicit_secret = False

    for match in LOCAL_PATH_RE.finditer(line):
        findings.append(
            Finding(
                path=path,
                line=line_no,
                column=match.start() + 1,
                rule="local-path",
                detail=match.group(0),
            )
        )

    for match in OPENAI_KEY_RE.finditer(line):
        saw_explicit_secret = True
        findings.append(
            Finding(
                path=path,
                line=line_no,
                column=match.start() + 1,
                rule="secret-token",
                detail="openai-style token",
            )
        )

    for match in AWS_KEY_RE.finditer(line):
        saw_explicit_secret = True
        findings.append(
            Finding(
                path=path,
                line=line_no,
                column=match.start() + 1,
                rule="secret-token",
                detail="aws access key",
            )
        )

    if saw_explicit_secret:
        return findings

    for match in SECRET_ASSIGNMENT_RE.finditer(line):
        value = match.group("value")
        if _is_safe_placeholder(value):
            continue
        if _is_code_reference(line, match):
            continue
        findings.append(
            Finding(
                path=path,
                line=line_no,
                column=match.start() + 1,
                rule="secret-assignment",
                detail="secret-like assignment",
            )
        )

    return findings


def scan_file(path: Path) -> list[Finding]:
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError):
        return []
    except UnicodeDecodeError:
        return []

    findings: list[Finding] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        findings.extend(scan_line(path, line_no, line))
    return findings


def default_scan_paths() -> list[Path]:
    candidates: list[Path] = []
    for relative in ("app", "docs", "scripts", "tests", ".github", ".pre-commit-config.yaml", "Makefile", "pyproject.toml"):
        path = REPO_ROOT / relative
        if path.is_file():
            candidates.append(path)
            continue
        if path.is_dir():
            candidates.extend(sorted(child for child in path.rglob("*") if child.is_file()))
    return candidates


def _git_tracked_files() -> list[Path]:
    """Every file in the index, which is what a push can actually carry.

    The automated scan was delta-only, and a delta sees only what changed after
    the delta existed: a file that predates the workflow, or that arrived in a
    squash-merge, is scanned once and then never again, and a new rule is never
    applied to what is already committed.

    Git's index is the source of truth rather than `default_scan_paths()`: that
    allowlist misses `experiments/`, `.framework/` and most root files, while
    also walking untracked working-tree files that no push can carry.

    NUL-separated on purpose -- a newline in a filename would otherwise split
    one path into two unreadable ones, inflating the count while never scanning
    the file. `check=True` so a failing `git` fails the run instead of yielding
    an empty list that reads like a clean repository.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return [REPO_ROOT / name for name in result.stdout.split("\0") if name]


def _git_changed_files(base_ref: str, head_ref: str) -> list[Path]:
    cmd = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMRTUXB",
        base_ref,
        head_ref,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _format_finding(finding: Finding) -> str:
    return f"{finding.path}:{finding.line}:{finding.column}: {finding.rule}: {finding.detail}"


def _iter_files_from_args(paths: Sequence[str]) -> Iterable[Path]:
    for raw in paths:
        if raw.startswith("-"):
            raise ValueError(f"unexpected option-like path: {raw}")
        yield Path(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan files for local paths and lightweight secret patterns.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files to scan. Usually provided by pre-commit.",
    )
    parser.add_argument(
        "--changed-from",
        dest="changed_from",
        help="Scan files changed between two git refs.",
    )
    parser.add_argument(
        "--changed-to",
        dest="changed_to",
        help="Scan files changed between two git refs.",
    )
    parser.add_argument(
        "--all-tracked",
        dest="all_tracked",
        action="store_true",
        help="Scan every file tracked by git. Used for the full-repository run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if bool(args.changed_from) ^ bool(args.changed_to):
        parser.error("--changed-from and --changed-to must be used together")

    if args.all_tracked and (args.changed_from or args.changed_to or args.paths):
        # Two scopes in one invocation means one is silently discarded, and the
        # mode reported below would name only the winner.
        parser.error("--all-tracked cannot be combined with paths or --changed-from/--changed-to")

    if args.all_tracked:
        mode = "all-tracked"
        paths = _git_tracked_files()
        if not paths:
            # An empty list scans nothing and would print `0 files checked` in
            # green -- indistinguishable from full coverage, while providing
            # none. A bad cwd or a broken checkout gets reported, never passed.
            print(
                "guardrails scan failed (mode=all-tracked): no tracked files found",
                file=sys.stderr,
            )
            return 1
    elif args.changed_from and args.changed_to:
        mode = "changed"
        paths = _git_changed_files(args.changed_from, args.changed_to)
    elif args.paths:
        mode = "explicit"
        paths = list(_iter_files_from_args(args.paths))
    else:
        mode = "default-paths"
        paths = default_scan_paths()

    findings: list[Finding] = []
    for path in paths:
        findings.extend(scan_file(path))

    if findings:
        # The mode belongs on both branches: a scan that does not say what it
        # covered is not auditable, which is how two base-resolution defects
        # survived in CI while reporting confidently.
        print(f"guardrails scan failed (mode={mode}):", file=sys.stderr)
        for finding in findings:
            print(_format_finding(finding), file=sys.stderr)
        return 1

    print(f"guardrails scan passed (mode={mode}, {len(paths)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
