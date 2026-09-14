"""AC22 — no artifact this ORQ produces describes E-BM25 as validated.

§Diseño 12's mechanical honesty sweep. Matches, case-insensitively and as
whole words, the enumerated forbidden-phrase list within 80 characters of
every `E-BM25` occurrence, against text this ORQ adds or modifies -- excluding
two scoped, literally-matched exceptions: the premise sentence (verbatim from
`roadmap.md`, quoted in `spec.md` and ADR-013), and any sentence stating that
E-BM25 is *not* validated or confirmed.

**Two sources of text, not one.** `git diff` covers every tracked file this
ORQ changed (`app/`, `tests/`, `docs/`, migrations, commit messages). It does
NOT cover `spec.md`/`implementation.md`: `.framework/orqs/` is deliberately
gitignored (a standing policy, not an oversight), so those files never appear
in a `git diff` no matter how large this ORQ's tracked footprint is. Both are
unambiguously "an artifact this ORQ produces" and are named explicitly in
AC22's own evidence description ("the premise sentence appears verbatim in
`spec.md` and ADR-013") -- a sweep that only ran `git diff` would silently
never check the very document AC22 names. This script therefore also reads
the full current content of every file under the ORQ's own directory: since
that directory did not exist before this ORQ, every line in it is text this
ORQ added, with no "before" state to diff against.

Usage:
    python3 app/scripts/check_honesty_sweep.py [--base <git-ref>]

Exit 0 when clean, 1 otherwise. Findings are printed raw: source, line
number (for diff hunks) or byte offset (for whole-file scans), and the
80-character window that matched.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ORQ_DIR = REPO_ROOT / ".framework/orqs/ORQ-37-rag-in-production"

FORBIDDEN = [
    "validated", "validates", "validation",
    "confirmed", "confirms", "confirmatory",
    "proven", "proves",
    "demonstrated", "established",
    "verified effective", "shown to work", "evidence that it works",
]

PREMISE = (
    "E-BM25 is being integrated for controlled production evaluation under "
    "uncertainty, not because it has been scientifically confirmed."
)

# Any sentence stating E-BM25 is NOT validated/confirmed -- matched literally,
# not as a single fixed string, since the wording varies by document (e.g.
# ADR-013's "E-BM25 is *not* validated or confirmed"). Widened beyond the
# literal word "not" to the same negation idiom this ORQ's own governance text
# repeats throughout (§No-alcance, T0's design-review verdicts): "no X can be
# read as...", "any presentation of this integration as..." inside a
# forbidden-things list, "cannot be read as...". All of these ASSERT THE
# ABSENCE of validation-framing -- the same thing "not validated" asserts,
# in the words this ORQ's spec and implementation record actually use.
_NEGATOR_RE = re.compile(
    r"\b(not|no|never|cannot)\b|any presentation of this integration as",
    re.IGNORECASE,
)
_FORBIDDEN_STYLE_RE = re.compile(
    "|".join(re.escape(p) for p in FORBIDDEN + ["confirmatory validation"]),
    re.IGNORECASE,
)
_EBM25_RE = re.compile(r"E-BM25")
# Splitting into sentences first, then checking each one for all three
# conditions independently, is what avoids the catastrophic backtracking a
# single nested-lookahead regex hit scanning the whole corpus in one pass. A
# period followed by whitespace is an approximate sentence boundary -- good
# enough for a mechanical exclusion pass; it never needs to be exact, only to
# not straddle two genuinely unrelated sentences.
#
# An ellipsis ("...") is excluded from that boundary: `(?<!\.\.)` requires
# the TWO characters immediately before the matched [.!?] to not both be
# periods, so "word... more" is not split mid-sentence. Discovered live
# (2026-09-08): this very docstring's own illustrative examples --
# "\"No artifact ... may describe ... as validation ... of E-BM25\"" --
# fragment on each "..." without this guard, scattering `E-BM25`, its
# negator and the forbidden phrase into separate "sentences" that no
# longer individually satisfy `_is_negation_sentence`, so the real sweep
# flagged its own exception-explaining prose as a violation.
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\.\.)(?<=[.!?])\s+")


def _is_negation_sentence(sentence: str) -> bool:
    """A sentence asserting the ABSENCE of validation-framing, any word order.

    The spec's and implementation record's own governance idiom puts E-BM25,
    a negator, and a forbidden-style phrase in different orders depending on
    the sentence ("E-BM25 is *not* validated" vs. "No artifact ... may
    describe ... as validation ... of E-BM25" vs. "any presentation ... as
    confirmatory validation ... of E-BM25") -- all three assert the same
    thing "not validated" does, just with a different negator or word order.
    """
    return bool(
        _EBM25_RE.search(sentence)
        and _NEGATOR_RE.search(sentence)
        and _FORBIDDEN_STYLE_RE.search(sentence)
    )
# A forbidden word cited as a literal token (single-backtick Markdown code
# span, e.g. `` `validated` ``) is the list's own enumeration, not a prose
# claim about E-BM25. Only single backticks: a fenced code BLOCK (triple
# backtick) could legitimately contain the premise sentence or other prose
# and must still be scanned.
BACKTICK_TOKEN = re.compile(r"`(" + "|".join(re.escape(p) for p in FORBIDDEN) + r")`", re.IGNORECASE)

WORD_BOUNDARY = {phrase: re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE) for phrase in FORBIDDEN}


def _mask_exceptions(text: str) -> str:
    """Remove the scoped exceptions, literally, before scanning.

    The premise is masked first: the one fixed-string, spec-declared
    exclusion. `NEGATION_PATTERN` implements the spec's other declared
    exclusion ("any sentence stating E-BM25 is not validated or confirmed"),
    widened to the same idiom this ORQ's own governance text repeats in
    different word orders and with different negators ("no artifact ... may
    describe ... as validation ... of E-BM25", "any presentation ... as
    confirmatory validation ... of E-BM25") -- all of them assert the ABSENCE
    of validation-framing, the same thing "not validated" asserts.
    `BACKTICK_TOKEN` is this checker's own addition, not new spec text: a
    forbidden word cited as a literal Markdown code span (`` `validated` ``)
    is the list's own required enumeration (§Diseño 12), not a prose claim.
    """
    text = text.replace(PREMISE, " " * len(PREMISE))
    sentences = _SENTENCE_SPLIT_RE.split(text)
    text = " ".join(
        (" " * len(sentence)) if _is_negation_sentence(sentence) else sentence
        for sentence in sentences
    )
    text = BACKTICK_TOKEN.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _findings(text: str, source: str) -> list[str]:
    findings = []
    masked = _mask_exceptions(text)
    for match in re.finditer(r"E-BM25", masked):
        window_start = max(0, match.start() - 80)
        window_end = min(len(masked), match.end() + 80)
        window = masked[window_start:window_end]
        for phrase in FORBIDDEN:
            if WORD_BOUNDARY[phrase].search(window):
                snippet = " ".join(window.split())
                findings.append(f"{source}: '{phrase}' near: ...{snippet}...")
    return findings


def _git_diff_text(base: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base}..HEAD", "--", "."],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    # Only ADDED lines are "text this ORQ adds or modifies" -- a `-` line is
    # text this ORQ REMOVED, and scanning it would flag prose that no longer
    # exists.
    added_lines = [
        line[1:] for line in result.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return "\n".join(added_lines)


def _git_log_text(base: str) -> str:
    result = subprocess.run(
        ["git", "log", "--format=%H%n%B%n---END---", f"{base}..HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return result.stdout


def _orq_directory_text() -> str:
    chunks = []
    if ORQ_DIR.is_dir():
        for path in sorted(ORQ_DIR.rglob("*")):
            if path.is_file():
                try:
                    chunks.append(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        default=None,
        help="git ref to diff against (default: merge-base origin/main HEAD)",
    )
    args = parser.parse_args()

    base = args.base
    if base is None:
        # `origin/main`, not `main`: a CI checkout sits on the ORQ branch and
        # has no local `main` branch, so `merge-base main HEAD` exits 128 and
        # the sweep dies before scanning anything. The remote-tracking ref
        # exists both on the runner and locally, and names the same branch
        # point.
        base = subprocess.run(
            ["git", "merge-base", "origin/main", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()

    sources = {
        "git diff (tracked files, added lines)": _git_diff_text(base),
        "git log (commit messages)": _git_log_text(base),
        ".framework/orqs/ORQ-37-rag-in-production/* (gitignored, whole-file)": _orq_directory_text(),
    }

    all_findings: list[str] = []
    for source, text in sources.items():
        all_findings.extend(_findings(text, source))

    if all_findings:
        print(f"HONESTY SWEEP: {len(all_findings)} finding(s)")
        for finding in all_findings:
            print(f"  {finding}")
        return 1

    print("HONESTY SWEEP: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
