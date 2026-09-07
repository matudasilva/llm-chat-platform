"""Additive index: (conversation_id, sequence) on messages

Revision ID: d29e6a1f4c87
Revises: c8f2a7d15b03
Create Date: 2026-09-07

ORQ-37 T12 / AC15, discharging the `(conversation_id, sequence)` half of
ADR-011's index debt. The existing `ix_messages_conversation_id_created_at`
(`4b29d461d571`) covers `(conversation_id, created_at)`; it does not support
an `ORDER BY sequence` plan, which is what the operational history read
(T12's `list_recent_messages_for_conversation`, `ORDER BY sequence DESC
LIMIT n`) needs to run as an index-only top-N scan rather than a sort over
every row of the conversation.

**This discharges only the `(conversation_id, sequence)` half.** ADR-011's
debt also names an index involving `tenant_id`; that half is undischarged and
is not silently assumed here (AC15's own text says so).

Purely additive: no column changes, no data migration, nothing that could make
the operational read return different rows -- only a plan the planner may now
choose. Downgrade drops the index and nothing else.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d29e6a1f4c87"
down_revision: Union[str, None] = "c8f2a7d15b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_messages_conversation_id_sequence"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "messages",
        ["conversation_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="messages")
