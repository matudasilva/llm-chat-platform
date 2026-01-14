"""merge heads 3a8de + 742cef

Revision ID: 52491fe56521
Revises: 3a8de89a9ee7, 742cef87b944
Create Date: 2026-01-14 04:08:34.266457

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52491fe56521'
down_revision: Union[str, None] = ('3a8de89a9ee7', '742cef87b944')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
