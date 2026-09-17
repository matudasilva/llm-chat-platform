"""No artifact in this repository describes E-BM25 as validated.

Originally ORQ-37's AC22 (§Diseño 12). Matches, case-insensitively and as
whole words, the enumerated forbidden-phrase list within 80 characters of
every `E-BM25` occurrence -- excluding two scoped, literally-matched
exceptions: the premise sentence (verbatim from `roadmap.md`, quoted in
`spec.md` and ADR-013), and any sentence stating that E-BM25 is *not*
validated or confirmed.

**Why the default scans the versioned repository rather than a delta.** This
began as branch tooling: it diffed against `merge-base origin/main HEAD` and
additionally read ORQ-37's own gitignored directory. Both sources were
delta-shaped, and once ORQ-37 was promoted that base *is* HEAD on `main`, so
`git diff` and `git log` both went empty -- while the ORQ directory, being
gitignored under `artifact_policy: hybrid`, is absent from every clone and
every CI checkout. The sweep therefore scanned zero characters on `main` and
printed `clean`, which is worse than not running: it looked like enforcement.

The constraint did not expire with the ORQ. `ebm25_enabled` ships on `main`,
ADR-013 is Accepted, and E-BM25 remains unvalidated -- which is exactly the
condition that makes the constraint necessary. ADR-013 states that no artifact
can describe E-BM25's status without tripping this sweep; that claim is only
true if the sweep reads what the repository currently says. So the detection
engine is untouched and the wiring is what changed: the default reads every
file git tracks, which is also what a reader of this repository can see.

`--base` keeps delta analysis as an explicit mode -- the right question on a
feature branch, where what matters is what that branch added.

Usage:
    python3 app/scripts/check_honesty_sweep.py            # every tracked file
    python3 app/scripts/check_honesty_sweep.py --base <git-ref>   # a delta

Exit 0 when clean, 1 otherwise -- and 1, never 0, when the scan read nothing
at all, since zero findings over zero text is indistinguishable in an exit
code from a repository that is genuinely clean.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from typing import Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

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

# The largest region that may claim the negation exception.
#
# `_is_negation_sentence` requires only that `E-BM25`, a negator and a
# forbidden phrase all appear *somewhere* in the same pseudo-sentence, with no
# proximity between them, and `_mask_exceptions` then blanks that whole region.
# The splitter above breaks on `[.!?]` + whitespace, which suits prose and
# produces enormous regions in text that carries no such boundary for hundreds
# of characters -- source code, YAML, Markdown tables. One negator anywhere
# inside then pardons every genuine claim sharing the region.
#
# Measured over the 452 tracked files, across the 19 negation regions that
# actually exclude something:
#
#     largest legitimate region observed    747  (ADR-013's rule bullet)
#     smallest over-masked region observed 2083  (tests/core/test_honesty_sweep.py)
#                                          5680  (experiments/.../guards.py)
#
# Nothing falls between 747 and 2083, so every threshold in that interval
# behaves identically on this corpus. 1000 is chosen for margin, not for being
# the smallest that passes: 750 also passes today but sits 3 characters above
# the largest legitimate region, so one edit to ADR-013 would begin flagging
# the document that defines the rule. 1000 leaves +253 (+34%) over the largest
# legitimate region and -1083 (-52%) under the smallest over-masked one.
#
# **This is a mitigation, not a fix.** It bounds the blast radius of an
# unbounded exception; it does not make the exception precise. A negator and a
# genuine claim inside the same *small* region are still both masked:
#
#     x = "<marker> is not validated"
#     y = "Testing has proven <marker> works"
#
# is 67 characters and stays undetected under any threshold. Closing that
# class means binding the negator to the specific forbidden phrase rather than
# to the region, which is a different change with a different blast radius.
# `test_the_short_region_false_negative_is_documented_as_still_open` keeps the
# limit visible.
MAX_NEGATION_SPAN = 1000


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
        (" " * len(sentence))
        if _is_negation_sentence(sentence) and len(sentence) <= MAX_NEGATION_SPAN
        else sentence
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


def _tracked_files() -> list[pathlib.Path]:
    """Every file git tracks -- what a reader of this repository can see.

    NUL-separated so a newline in a filename cannot split one path into two
    unreadable ones. `check=True` so a failing `git` is reported rather than
    silently yielding a short list that scans a prefix of the repository.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [REPO_ROOT / name for name in result.stdout.split("\0") if name]


def _tracked_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in _tracked_files():
        try:
            sources[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
    return sources


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        default=None,
        help="git ref to diff against; selects delta mode instead of the "
             "default scan of every tracked file",
    )
    args = parser.parse_args(argv)

    if args.base is not None:
        mode = "delta"
        sources = {
            "git diff (tracked files, added lines)": _git_diff_text(args.base),
            "git log (commit messages)": _git_log_text(args.base),
        }
    else:
        mode = "tracked"
        sources = _tracked_sources()

    scanned_files = len(sources)
    scanned_chars = sum(len(text) for text in sources.values())

    all_findings: list[str] = []
    for source, text in sources.items():
        all_findings.extend(_findings(text, source))

    summary = f"mode={mode}, {scanned_files} files, {scanned_chars} chars"

    # A delta may legitimately be empty -- a branch that changed nothing. The
    # default mode may not: reading no text at all means the scan is broken,
    # not that the repository is clean, and reporting `clean` for it is how
    # this check spent the whole ORQ-37 promotion looking like enforcement
    # while asserting nothing.
    if mode == "tracked" and scanned_chars == 0:
        print(f"HONESTY SWEEP: scanned nothing ({summary}) -- refusing to report clean")
        return 1

    if all_findings:
        print(f"HONESTY SWEEP: {len(all_findings)} finding(s) ({summary})")
        for finding in all_findings:
            print(f"  {finding}")
        return 1

    print(f"HONESTY SWEEP: clean ({summary} scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
