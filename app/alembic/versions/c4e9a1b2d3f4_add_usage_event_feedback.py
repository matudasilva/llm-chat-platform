"""add usage event feedback

Revision ID: c4e9a1b2d3f4
Revises: b7f3c9d1a204
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e9a1b2d3f4"
down_revision: Union[str, None] = "b7f3c9d1a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("feedback", sa.String(length=8), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("feedback_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_usage_events_feedback",
        "usage_events",
        "feedback IS NULL OR feedback IN ('up', 'down')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_usage_events_feedback", "usage_events", type_="check")
    op.drop_column("usage_events", "feedback_updated_at")
    op.drop_column("usage_events", "feedback")
