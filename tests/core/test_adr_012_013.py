"""ORQ-37 T20 — ADR-012/ADR-013 content guarantees (AC22).

AC22's own mechanical sweep across the full ORQ diff is T21's task. This file
pins the narrower, directly-checkable facts T20 is responsible for: the
premise sentence's verbatim presence, the amendment cross-references, and the
six-term retention contract's presence in ADR-012 (mirroring AC33's own
`grep -F` evidence pattern from T14).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_012 = REPO_ROOT / "docs/adr/012-rag-production-observability-and-history-hardening.md"
ADR_013 = REPO_ROOT / "docs/adr/013-ebm25-controlled-evaluation-port.md"
ADR_008 = REPO_ROOT / "docs/adr/008-rag-generation-and-feedback-boundaries.md"
ADR_011 = REPO_ROOT / "docs/adr/011-conversation-history-substrate.md"
TECH_STACK = REPO_ROOT / ".framework/constitution/tech-stack.md"
SPEC = REPO_ROOT / ".framework/orqs/ORQ-37-rag-in-production/spec.md"

# `.framework/orqs/` is deliberately gitignored under `artifact_policy: hybrid`,
# so ORQ specs exist in a working copy but never in a fresh checkout. A test
# that reads one can only assert where its evidence is present; anywhere else
# it must skip and say why, rather than fail for a reason unrelated to its
# claim. The condition is the artifact's own absence, not `CI` -- a clone
# without artifacts behaves the same wherever it runs.
requires_orq_spec = pytest.mark.skipif(
    not SPEC.is_file(),
    reason=(
        f"{SPEC.relative_to(REPO_ROOT)} is absent: `.framework/orqs/` is "
        "intentionally gitignored under `artifact_policy: hybrid`, so it is "
        "not part of any checkout. This assertion runs where the ORQ artifacts "
        "exist."
    ),
)

PREMISE = (
    "E-BM25 is being integrated for controlled production evaluation under "
    "uncertainty, not because it has been scientifically confirmed."
)


def test_both_adrs_exist() -> None:
    assert ADR_012.exists()
    assert ADR_013.exists()


def test_premise_appears_verbatim_on_one_line_in_adr_013() -> None:
    # A plain `grep -F` for the exact sentence must find it -- not merely a
    # semantically-equivalent paraphrase, and not split across a soft-wrapped
    # line boundary that would defeat a literal-string search.
    text = ADR_013.read_text(encoding="utf-8")
    assert PREMISE in text


@requires_orq_spec
def test_spec_carries_the_same_premise_even_though_it_is_line_wrapped() -> None:
    # spec.md's own blockquote soft-wraps the sentence across two lines
    # (`> "E-BM25 is being integrated ... under\n> uncertainty, ...`). A plain
    # single-line `grep -F` will not match it there; joining the blockquote's
    # lines is what recovers the same sentence ADR-013 carries on one line.
    # This is a known, pre-existing tooling consideration for AC22's evidence
    # step (T21), not something T20 may fix by editing the reviewed spec.
    text = SPEC.read_text(encoding="utf-8")
    start = text.find('> "E-BM25 is being integrated')
    assert start != -1, "premise blockquote not found in spec.md"
    end = text.find("\n\n", start)
    block = text[start:end]
    joined = " ".join(line[2:] if line.startswith("> ") else line for line in block.split("\n"))
    assert joined.strip('"') == PREMISE


def test_adr_012_records_the_six_retention_terms() -> None:
    text = ADR_012.read_text(encoding="utf-8")
    for term in ("Window", "Owner", "Procedure", "cadence", "delay", "Evidence of execution"):
        assert term in text


def test_adr_012_states_the_37_day_breach_threshold() -> None:
    assert "37" in ADR_012.read_text(encoding="utf-8")


def test_adr_012_discloses_r19_as_residual_not_mitigated() -> None:
    text = ADR_012.read_text(encoding="utf-8").lower()
    assert "residual" in text
    assert "r19" in text


def test_adr_013_declares_all_four_divergences() -> None:
    text = ADR_013.read_text(encoding="utf-8")
    for term in ("Document unit", "Tie-break", "Query tokens", "Packing budget"):
        assert term in text


def test_adr_013_states_the_four_bm25_constants_by_value() -> None:
    text = ADR_013.read_text(encoding="utf-8")
    for constant in ("256", "TOP_K=5", "1.2", "0.75"):
        assert constant in text


# --- cross-references: amendments are recorded on BOTH sides ---------------


def test_adr_008_header_points_forward_to_both_amendments() -> None:
    header = ADR_008.read_text(encoding="utf-8").splitlines()[5]
    assert "ADR-012" in header
    assert "ADR-013" in header


def test_adr_011_header_points_forward_to_adr_012() -> None:
    header = ADR_011.read_text(encoding="utf-8").splitlines()[5]
    assert "ADR-012" in header


def test_adr_012_evidence_section_names_what_it_amends() -> None:
    text = ADR_012.read_text(encoding="utf-8")
    assert "docs/adr/008-rag-generation-and-feedback-boundaries.md" in text
    assert "docs/adr/011-conversation-history-substrate.md" in text


def test_adr_013_evidence_section_names_what_it_amends() -> None:
    text = ADR_013.read_text(encoding="utf-8")
    assert "docs/adr/008-rag-generation-and-feedback-boundaries.md" in text


def test_tech_stack_cache_sentence_no_longer_claims_full_history() -> None:
    text = TECH_STACK.read_text(encoding="utf-8")
    assert "full conversation history" not in text
    assert "bounded recent-window" in text


def test_tech_stack_records_the_otel_dependency() -> None:
    text = TECH_STACK.read_text(encoding="utf-8")
    assert "opentelemetry" in text.lower()
