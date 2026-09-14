"""ORQ-37 T14 — the rag_request_metrics table migration (AC33's statement half,
AC9's metrics-write half, AC34's rag_request_metrics half).

Hermetic, static checks -- same approach as `test_ops_grants_migration.py`
(T7) and `test_conversation_history_index_migration.py` (T12). A real
PostgreSQL corpus is needed to exercise the grants live; that is a separate
evidence phase, on request, the same split used for T7 and T12's AC15.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infra.db.base import Base
from app.models.rag_request_metrics import RagRequestMetrics  # noqa: F401

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/alembic/versions/e4b7f21c9a06_rag_request_metrics.py"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_down_revision_is_the_current_head(source: str) -> None:
    assert 'down_revision: Union[str, None] = "d29e6a1f4c87"' in source


def test_migration_creates_the_table(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert 'op.create_table(\n        "rag_request_metrics"' in upgrade


def test_request_instance_id_is_unique_not_null(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    line = next(l for l in upgrade.splitlines() if "request_instance_id" in l)
    assert "nullable=False" in line
    assert "unique=True" in line


def test_request_id_is_indexed_but_not_unique(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    column_line = next(
        l for l in upgrade.splitlines() if '"request_id"' in l and "sa.Column" in l
    )
    assert "unique=True" not in column_line
    assert "ix_rag_request_metrics_request_id" in upgrade


def _upgrade_grant_blocks(source: str) -> tuple[str, str]:
    """The two `op.execute(...)` DO-blocks in `upgrade()`, in source order.

    Splitting on `op.execute(` (not on the role constants, which are declared
    once at the top of the file and therefore appear in BOTH blocks) is what
    correctly isolates the runtime grant from the retention grant.
    """
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    _, runtime_and_after = upgrade.split("op.execute(", 1)
    runtime_block, retention_block = runtime_and_after.split("op.execute(", 1)
    return runtime_block, retention_block


def test_runtime_role_grant_is_insert_only(source: str) -> None:
    # §Diseño 7's corrected split: the runtime role must never gain SELECT or
    # DELETE on this table -- that was the earlier draft's mistake.
    runtime_block, _ = _upgrade_grant_blocks(source)
    assert "GRANT INSERT ON rag_request_metrics TO" in runtime_block
    assert "GRANT SELECT" not in runtime_block
    assert "GRANT DELETE" not in runtime_block


def test_retention_role_grant_is_select_and_delete_only(source: str) -> None:
    _, retention_block = _upgrade_grant_blocks(source)
    assert "GRANT SELECT, DELETE ON rag_request_metrics TO" in retention_block
    assert "GRANT INSERT" not in retention_block


def test_both_roles_are_existence_guarded(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert upgrade.count("SELECT 1 FROM pg_roles WHERE rolname") == 2


def test_no_rls_introduced(source: str) -> None:
    for forbidden in ("ROW LEVEL SECURITY", "CREATE POLICY"):
        assert forbidden not in source


def test_migration_never_touches_existing_tables(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    for existing_table in ("conversations", "messages", "usage_events"):
        assert f'"{existing_table}"' not in upgrade


def test_downgrade_drops_the_table_and_revokes_grants(source: str) -> None:
    downgrade = source.split("def downgrade()", 1)[1]
    assert 'op.drop_table("rag_request_metrics")' in downgrade
    assert "REVOKE ALL ON rag_request_metrics" in downgrade


def test_orm_model_matches_the_migration_columns(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    migration_columns = {
        line.strip().split('"')[1]
        for line in upgrade.splitlines()
        if line.strip().startswith('sa.Column("')
    }
    orm_columns = set(Base.metadata.tables["rag_request_metrics"].columns.keys())
    assert migration_columns == orm_columns
