"""ORQ-37 T14 — the published retention statement (AC33's statement half).

AC33's ADR-012 half -- formalizing the six-term contract into an ADR and the
ADR-008 amendments -- is T20's task (task table: "T20 | ADR-012 and ADR-013
..."), not T14's. This file closes only what T14 owns: that the operational
statement exists, is documented as manual (never automated), and its
predicate is exactly "older than the configured window and nothing else".
"""
from __future__ import annotations

import re
from pathlib import Path

DOC = (
    Path(__file__).resolve().parents[2]
    / "docs/observability/rag_request_metrics_retention.md"
)


def _text() -> str:
    assert DOC.exists(), f"missing retention statement: {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_document_exists_and_is_not_empty() -> None:
    assert len(_text()) > 200


def test_statement_deletes_by_created_at_only() -> None:
    text = _text()
    sql = re.search(r"```sql\n(.*?)\n```", text, re.DOTALL)
    assert sql, "no SQL statement block found"
    statement = sql.group(1)
    assert statement.strip().upper().startswith("DELETE FROM RAG_REQUEST_METRICS")
    assert "WHERE created_at <" in statement
    # Exactly the rows older than the window and nothing else: no LIMIT, no
    # join, no second predicate that could narrow or widen the deleted set.
    assert "LIMIT" not in statement.upper()
    assert "JOIN" not in statement.upper()
    assert statement.count("WHERE") == 1


def test_statement_uses_the_configured_retention_window() -> None:
    assert "retention_days" in _text()
    assert "rag_request_metrics_retention_days" in _text()


def test_states_no_automation_exists() -> None:
    text = _text().lower()
    for term in ("scheduler", "cron", "watchdog", "background worker"):
        assert term in text
    assert "not automated" in text or "no scheduler" in text


def test_declares_all_six_contract_terms() -> None:
    text = _text().lower()
    for term in ("window", "owner", "procedure", "cadence", "delay", "evidence"):
        assert term in text


def test_states_the_37_day_breach_threshold() -> None:
    assert "37" in _text()


def test_owner_is_a_real_assignment_not_a_placeholder() -> None:
    # INVERTED on 2026-09-12, not deleted. This guard previously required the
    # field to hold a placeholder, because this ORQ must not invent an
    # organizational decision -- and it never did: "Platform Operations" was
    # assigned by operator decision, which ADR-012 requires before production
    # enablement and places outside this ORQ's authority.
    #
    # The guard now protects the other direction, which is the one that
    # matters from here: the field must hold a real name, so an edit that
    # silently reverts it to a placeholder -- or blanks it -- fails here
    # rather than quietly reopening AC33's privacy-readiness gate.
    text = _text()
    assert "Platform Operations" in text
    for placeholder in ("<OPERATOR", "TBD", "to be assigned"):
        assert placeholder not in text, f"owner reverted to a placeholder: {placeholder!r}"


def test_gates_production_enablement() -> None:
    text = _text().lower()
    assert "rag_request_metrics_enabled" in text
    assert "false" in text
