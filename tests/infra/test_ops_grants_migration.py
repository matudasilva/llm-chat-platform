"""ORQ-37 T7 — static guards on the operational grants migration (AC34 B1 half).

AC34's evidence names two things: `@pytest.mark.postgres` grant tests and
"`git diff` shows no RLS statement". The first cannot run without a database.
This file asserts the second **hermetically**, by reading the migration itself,
so the no-RLS property is verified on every run rather than only when someone
sets `RAG_TEST_DATABASE_URL` — a property asserted only under an opt-in marker
is a property nobody checks.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/alembic/versions/c8f2a7d15b03_chat_ops_read_only_grants.py"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def statements(source: str) -> str:
    """Executable SQL only — the docstring legitimately mentions RLS."""
    body = source.split('"""', 2)[-1]
    return body.upper()


@pytest.mark.parametrize(
    "forbidden",
    [
        "ROW LEVEL SECURITY",
        "CREATE POLICY",
        "ALTER POLICY",
        "DROP POLICY",
    ],
)
def test_migration_introduces_no_rls(statements: str, forbidden: str) -> None:
    # §No-alcance: RLS on conversations/messages stays ADR-004 §5's standing
    # debt. Discharging it here would silently change the semantics of every
    # existing read path.
    assert forbidden not in statements, f"{forbidden} found in the migration body"


def test_grants_are_select_only(statements: str) -> None:
    granted = set(re.findall(r"GRANT\s+([A-Z, ]+?)\s+ON", statements))
    # `GRANT USAGE ON SCHEMA public` is required to reach the tables at all.
    assert granted == {"SELECT", "USAGE"}, granted


@pytest.mark.parametrize("table", ["conversations", "messages"])
def test_both_history_tables_are_granted(statements: str, table: str) -> None:
    assert f"GRANT SELECT ON {table.upper()}" in statements


def test_no_write_privilege_is_granted(statements: str) -> None:
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALL PRIVILEGES"):
        assert f"GRANT {privilege}" not in statements, privilege


def test_revoke_precedes_grant(statements: str) -> None:
    # The "cannot write" half of AC34 must be established by this migration,
    # not inherited from an assumption about a pristine cluster: privileges can
    # reach a role through PUBLIC or through a prior grant.
    for table in ("CONVERSATIONS", "MESSAGES"):
        revoke = statements.index(f"REVOKE ALL ON {table}")
        grant = statements.index(f"GRANT SELECT ON {table}")
        assert revoke < grant, table


def test_every_statement_is_role_guarded(source: str) -> None:
    # Reversible and side-effect-free where `chat_ops` was never provisioned —
    # the same guard ORQ-21 used, and what keeps the migration chain testable
    # against a bare Postgres.
    assert source.count("SELECT 1 FROM pg_roles WHERE rolname") == 2  # upgrade + downgrade


def test_migration_never_touches_the_role_itself(statements: str) -> None:
    # Roles are cluster-level; they are provisioned by
    # scripts/postgres-init/30-chat-ops-role.sh, never by Alembic.
    for statement in ("CREATE ROLE", "DROP ROLE", "ALTER ROLE"):
        assert statement not in statements, statement


def test_downgrade_revokes_and_does_not_re_grant(source: str) -> None:
    downgrade = source.split("def downgrade()", 1)[1].upper()
    assert "REVOKE ALL ON CONVERSATIONS" in downgrade
    assert "REVOKE ALL ON MESSAGES" in downgrade
    assert "GRANT" not in downgrade
