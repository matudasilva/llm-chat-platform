"""init (noop)

Revision ID: 8cb367cad8b4
Revises: None
Create Date: 2026-01-10

Initial baseline revision. This is intentionally a no-op to establish the
migration chain for future schema changes.
"""

from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "8cb367cad8b4"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
