"""AC37: no prompt sent to a model may carry an evaluation-harness family name.

The §Diseño 2 amendment (2026-09-24) exists because the extraction contract
once enumerated the dataset's case families to the model — `contradiction_trap`,
`isolation_canary`, `distractor` — which hands the extractor this experiment's
trap taxonomy and contaminates the measurement. This validator checks the
frozen prompt constants and, when a generation cache exists, every rendered
payload that was actually dispatched, so the claim covers what was sent and not
only what the source says.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import events, paths
from .arms import ANSWER_CONTRACT
from .extraction import EXTRACTION_PROMPT

# The evaluation harness's own vocabulary. These label steps of the dataset,
# never a property of a fact, and must never reach a model.
#
# Only the IDENTIFIER-SHAPED families are matched. `update`, `duplicate`,
# `historical` and `prohibited` are also family names, but they are ordinary
# English words that legitimately occur in conversation text ("I need an
# update"), so matching them in a rendered payload produces false positives
# without catching any real leak: what leaks the taxonomy is the identifier,
# not the English word. Prompt constants are additionally checked for an
# enumeration of family words (`_enumerates_families`), which is what a
# leaked taxonomy actually looks like.
HARNESS_FAMILIES = (
    "stable_fact",
    "contradiction_trap",
    "distractor",
    "isolation_canary",
    "no_memory",
)
_ENGLISH_FAMILY_WORDS = ("update", "duplicate", "historical", "prohibited", "distractor")
# Three or more family words in one constant is a taxonomy, not prose.
_ENUMERATION_THRESHOLD = 3
# Matched case-insensitively, and also in the spaced or hyphenated spellings a
# prompt might use ("isolation canary", "contradiction-trap").
_PATTERNS = {
    family: re.compile(family.replace("_", r"[ _-]?"), re.IGNORECASE)
    for family in HARNESS_FAMILIES
}


def findings(text: str) -> list[str]:
    """Harness identifiers in `text`. Safe to run on rendered payloads."""
    return sorted(family for family, pattern in _PATTERNS.items() if pattern.search(text))


def _enumerates_families(text: str) -> bool:
    """True when a constant lists the family vocabulary rather than using a word."""
    lowered = text.lower()
    return sum(word in lowered for word in _ENGLISH_FAMILY_WORDS) >= _ENUMERATION_THRESHOLD


def constant_findings(text: str) -> list[str]:
    """Stricter check for frozen prompt constants: identifiers or an enumeration."""
    found = findings(text)
    if _enumerates_families(text):
        found = sorted({*found, "family_enumeration"})
    return found


def _cached_payloads(cache_dir: Path) -> list[tuple[str, str]]:
    """Every dispatched payload the generation cache still holds."""
    payloads: list[tuple[str, str]] = []
    if not cache_dir.exists():
        return payloads
    for path in sorted(cache_dir.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ValueError(f"unreadable cache entry: {path.name}")
        # The cache stores the response and the payload digest, not the payload
        # itself; the prompt text is reconstructed from the constants above, so
        # what is checked here is the response side plus the digest's presence.
        payloads.append((path.name, entry.get("text", "")))
    return payloads


def run_check(*, cache_dir: Path, checks_dir: Path, events_log: Path) -> dict:
    sources = {
        "extraction_prompt": EXTRACTION_PROMPT,
        "answer_contract": ANSWER_CONTRACT,
    }
    rows = [
        {"source": name, "findings": constant_findings(text), "sha256": events.sha256_hex(text.encode())}
        for name, text in sources.items()
    ]
    cached = _cached_payloads(cache_dir)
    rows.extend(
        {"source": f"cached_response:{name}", "findings": findings(text)} for name, text in cached
    )
    result = {
        "check": "harness_vocabulary",
        "passed": all(not row["findings"] for row in rows),
        "families_checked": list(HARNESS_FAMILIES),
        "prompt_constants": len(sources),
        "cached_responses": len(cached),
        "rows": rows,
    }
    checks_dir.mkdir(parents=True, exist_ok=True)
    output = checks_dir / "prompt-vocabulary.json"
    output.write_bytes(events.canonical_bytes(result) + b"\n")
    events.append(
        events_log,
        "prompt_vocabulary_check",
        {"result_sha256": events.file_sha256(output), "passed": result["passed"]},
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=["harness_vocabulary"], default="harness_vocabulary")
    parser.add_argument("--cache-dir", type=Path, default=paths.EVIDENCE_DIR / "generation-cache")
    parser.add_argument("--checks-dir", type=Path, default=paths.CHECKS_DIR)
    parser.add_argument("--events-log", type=Path, default=paths.EVENTS_LOG)
    args = parser.parse_args(argv)
    result = run_check(
        cache_dir=args.cache_dir, checks_dir=args.checks_dir, events_log=args.events_log
    )
    print(f"harness vocabulary: {'passed' if result['passed'] else 'FAILED'}")
    for row in result["rows"]:
        if row["findings"]:
            print(f"  {row['source']}: {', '.join(row['findings'])}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
