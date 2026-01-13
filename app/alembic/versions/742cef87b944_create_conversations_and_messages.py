"""create conversations and messages

Revision ID: 742cef87b944
Revises: 4b29d461d571
Create Date: 2026-01-10

Restored migration file: the database is already stamped at this revision,
but the original revision file was missing from the repository/image.
This migration defines the schema so new environments can reproduce it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "742cef87b944"
down_revision: Union[str, None] = "4b29d461d571"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # conversations
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
    )

    # enum type for role (idempotent creation + prevent implicit create)
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typname = 'message_role'
        ) THEN
            CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
        END IF;
    END$$;
    """))

    role_enum = postgresql.ENUM(
        "user", "assistant", "system",
        name="message_role",
        create_type=False,
    )

    # messages
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index(
        "ix_messages_conversation_id_created_at",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )



def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.execute(sa.text("DROP TYPE IF EXISTS message_role;"))




