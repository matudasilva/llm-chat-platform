cat > ./app/alembic/versions/eee251fdccda_preserve_chain_noop.py <<'PY'
"""preserve chain (noop)

Revision ID: eee251fdccda
Revises: 52491fe56521
Create Date: 2026-01-14

This revision is intentionally a no-op. It exists to preserve the migration
chain because the database is stamped at this revision, but the original
revision file was missing from the repository/image.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "eee251fdccda"
down_revision: Union[str, None] = "52491fe56521"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
PY
