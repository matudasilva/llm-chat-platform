"""add conversation and message (noop)

Revision ID: 4b29d461d571
Revises: 9bc36b28b8eb
Create Date: 2026-01-10

This revision was previously generated as an empty migration (no-op).
It is kept to preserve the migration chain because the database already
stamped this revision in alembic_version.
"""

from typing import Sequence, Union
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "4b29d461d571"
down_revision: Union[str, None] = "9bc36b28b8eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
