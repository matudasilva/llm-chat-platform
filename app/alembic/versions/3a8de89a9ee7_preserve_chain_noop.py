"""preserve chain (noop)

Revision ID: 3a8de89a9ee7
Revises: 9bc36b28b8eb
Create Date: 2026-01-14

This revision is intentionally a no-op. It exists to preserve the migration
chain because the database was stamped at this revision in a previous state.
"""

from typing import Sequence, Union

revision: str = "3a8de89a9ee7"
down_revision: Union[str, None] = "9bc36b28b8eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
