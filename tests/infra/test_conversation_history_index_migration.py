"""ORQ-37 T12 — the (conversation_id, sequence) index migration (AC15).

Hermetic, static checks over the migration source and the ORM metadata --
mirroring `tests/infra/test_ops_grants_migration.py`'s approach for T7. The
`EXPLAIN`/latency half of AC15 needs a real PostgreSQL corpus at a stated
conversation length and is deliberately NOT attempted here; see
`implementation.md` for why it is treated as a separate evidence phase.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infra.db.base import Base
from app.models.message import Message  # noqa: F401  (registers the table)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/alembic/versions/d29e6a1f4c87_messages_conversation_id_sequence_index.py"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_down_revision_is_the_current_head(source: str) -> None:
    # Pins the chain link: if T7's grants migration ever stops being head,
    # this fails loudly instead of silently forking the chain.
    assert 'down_revision: Union[str, None] = "c8f2a7d15b03"' in source


def test_migration_creates_the_named_index_on_messages(source: str) -> None:
    assert 'op.create_index(\n        INDEX_NAME,\n        "messages",' in source
    assert 'INDEX_NAME = "ix_messages_conversation_id_sequence"' in source


def test_migration_columns_are_conversation_id_then_sequence(source: str) -> None:
    assert '["conversation_id", "sequence"]' in source


def test_downgrade_drops_only_the_index(source: str) -> None:
    downgrade = source.split("def downgrade()", 1)[1]
    assert "op.drop_index(INDEX_NAME" in downgrade
    # Purely additive: downgrade must not touch any table, column or data.
    for destructive in ("drop_table", "drop_column", "DELETE", "DROP TABLE"):
        assert destructive not in downgrade


def test_migration_introduces_no_column_or_data_change(source: str) -> None:
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    for forbidden in ("add_column", "drop_column", "alter_column", "execute("):
        assert forbidden not in upgrade


def test_docstring_states_only_one_half_of_the_debt_is_discharged(source: str) -> None:
    # AC15's own text: "ADR-011's debt also names an index involving
    # tenant_id; this discharges only the former, and says so."
    assert "tenant_id" in source
    assert "undischarged" in source


def test_orm_metadata_and_migration_agree() -> None:
    # An autogenerate diff against a model missing this index would propose
    # dropping it; this pins that the model and the migration stay in sync.
    index_names = {ix.name for ix in Base.metadata.tables["messages"].indexes}
    assert "ix_messages_conversation_id_sequence" in index_names


def test_orm_index_columns_match_the_migration() -> None:
    index = next(
        ix
        for ix in Base.metadata.tables["messages"].indexes
        if ix.name == "ix_messages_conversation_id_sequence"
    )
    assert [c.name for c in index.columns] == ["conversation_id", "sequence"]
