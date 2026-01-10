"""describe change (noop)

Revision ID: 9bc36b28b8eb
Revises: 8cb367cad8b4
Create Date: 2026-01-10

This revision is intentionally a no-op. It exists to preserve the migration
chain because the database has been stamped/applied through this revision.
"""

from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "9bc36b28b8eb"
down_revision: Union[str, None] = "8cb367cad8b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
