"""create usage_events

Revision ID: d4dd07072605
Revises: ef64dc6ccefd
Create Date: 2026-01-14

Creates usage_events table for usage/telemetry tracking.
Idempotent: if table/indexes/constraints already exist, it will not fail.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4dd07072605"
down_revision: Union[str, None] = "ef64dc6ccefd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # If the table doesn't exist, create it with constraints
    exists = bind.execute(sa.text("SELECT to_regclass('public.usage_events') IS NOT NULL")).scalar()
    if not exists:
        op.create_table(
            "usage_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "conversation_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("conversations.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "message_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("messages.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("model_version", sa.String(length=128), nullable=False),
            sa.Column("prompt_version", sa.String(length=64), nullable=False),
            sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    # Indexes (safe even if table already existed)
    # Postgres supports CREATE INDEX IF NOT EXISTS
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_usage_events_request_id ON usage_events (request_id);'
    ))
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_usage_events_conversation_ts ON usage_events (conversation_id, "timestamp");'
    ))
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_usage_events_message_id ON usage_events (message_id);'
    ))


def downgrade() -> None:
    # Conservative downgrade: drop indexes then table (if exists)
    op.execute(sa.text("DROP INDEX IF EXISTS ix_usage_events_message_id;"))
    op.execute(sa.text('DROP INDEX IF EXISTS ix_usage_events_conversation_ts;'))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_usage_events_request_id;"))
    op.execute(sa.text("DROP TABLE IF EXISTS usage_events;"))
