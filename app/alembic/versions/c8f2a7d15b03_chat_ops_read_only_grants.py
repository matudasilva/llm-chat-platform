"""Least-privilege operational role: read-only grants on conversations/messages

Revision ID: c8f2a7d15b03
Revises: f1e2d3c4b5a6
Create Date: 2026-09-05

ORQ-37 T7 / §Diseño 7, Gate B1 half. Grants the operational (`chat_ops`) role
exactly `SELECT` on `conversations` and `messages` — the credential the history
read path uses — and nothing else.

The role itself is provisioned outside Alembic
(`scripts/postgres-init/30-chat-ops-role.sh`) because roles are cluster-level
and `CREATE ROLE` is not idempotent per database; the same split ORQ-21 used
for `rag_app`. Everything here is therefore guarded by a role-existence check
so the migration stays reversible and side-effect-free on a database where
`chat_ops` was never provisioned (a bare Postgres used only to test the
migration chain).

`REVOKE ALL` precedes the `GRANT` deliberately. The "cannot write" half of
AC34 must be a property this migration ESTABLISHES, not one inherited from an
assumption about what a fresh role happens to start with: privileges can reach
a role through `PUBLIC` or through a prior grant, and an acceptance criterion
that only holds on a pristine cluster is not an acceptance criterion.

**No RLS is introduced.** RLS on `conversations`/`messages` remains the
standing debt ADR-004 §5 records and this ORQ's §No-alcance excludes; AC34
asserts its absence. Nothing here enables, forces, or creates a policy.

Downgrade revokes the grants and never touches the role.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8f2a7d15b03"
down_revision: Union[str, None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPS_ROLE = "chat_ops"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
                    GRANT USAGE ON SCHEMA public TO {OPS_ROLE};

                    REVOKE ALL ON conversations FROM {OPS_ROLE};
                    REVOKE ALL ON messages FROM {OPS_ROLE};

                    GRANT SELECT ON conversations TO {OPS_ROLE};
                    GRANT SELECT ON messages TO {OPS_ROLE};
                END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
                    REVOKE ALL ON conversations FROM {OPS_ROLE};
                    REVOKE ALL ON messages FROM {OPS_ROLE};
                END IF;
            END
            $$;
            """
        )
    )
