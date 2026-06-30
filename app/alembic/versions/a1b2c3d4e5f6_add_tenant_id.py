"""add tenant_id to conversations and messages

Revision ID: a1b2c3d4e5f6
Revises: d4dd07072605
Create Date: 2026-06-30

Adds tenant_id VARCHAR(64) NOT NULL DEFAULT 'default' to conversations and messages.
Adds composite index (tenant_id, created_at) on conversations for per-tenant queries.
Migration is reversible: downgrade drops the index then the columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d4dd07072605"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "tenant_id",
            sa.String(64),
            nullable=False,
            server_default="default",
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "tenant_id",
            sa.String(64),
            nullable=False,
            server_default="default",
        ),
    )
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_conversations_tenant_id_created_at "
        "ON conversations (tenant_id, created_at);"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DROP INDEX IF EXISTS ix_conversations_tenant_id_created_at;"
    ))
    op.drop_column("conversations", "tenant_id")
    op.drop_column("messages", "tenant_id")
