"""add database-generated message sequence

Revision ID: f1e2d3c4b5a6
Revises: c4e9a1b2d3f4
Create Date: 2026-08-10

Adds the database-owned ordering key used by all message readers. PostgreSQL
assigns identity values to existing rows while adding the non-null column and
to every later insert; application code never supplies the value.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, None] = "c4e9a1b2d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "sequence")
