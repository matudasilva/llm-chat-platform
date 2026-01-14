"""preserve chain (noop)

Revision ID: ef64dc6ccefd
Revises: 56edddae02d1
Create Date: 2026-01-14 20:18:19.919241

This revision is intentionally a no-op. It exists because an earlier autogenerate
created an empty migration; we keep it to preserve the revision chain.
"""

from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "ef64dc6ccefd"
down_revision: Union[str, None] = "56edddae02d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
