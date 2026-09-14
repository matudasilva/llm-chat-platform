"""rag_request_metrics table + split grants (runtime INSERT-only, retention SELECT/DELETE)

Revision ID: e4b7f21c9a06
Revises: d29e6a1f4c87
Create Date: 2026-09-07

ORQ-37 T14 / §Diseño 6, Gate B2. Creates the per-request metrics table and its
grants, split exactly as §Diseño 7 specifies:

  * `chat_ops` (the runtime role, T7): `INSERT` only. It cannot read the table
    back or delete from it -- metrics are append-only from the application's
    side, so audit integrity does not depend on the request path being
    uncompromised.
  * `chat_ops_retention` (a SEPARATE, operator-held credential, provisioned by
    `scripts/postgres-init/40-chat-ops-retention-role.sh`, never in the app's
    configuration): `SELECT`/`DELETE` on this table and nothing else.

An earlier draft (§Diseño 7) gave the request-serving credential `DELETE` and
a broad `SELECT`, which meant a compromised application path could erase or
read cross-tenant telemetry. This migration establishes the corrected split
from the start, the same way `c8f2a7d15b03` established `chat_ops`'s read-only
grants on conversations/messages.

**No RLS is introduced.** Both role-existence checks guard every statement, so
this stays reversible and side-effect-free on a database where either role was
never provisioned (a bare Postgres testing the migration chain in isolation).

Purely additive: a new table, no change to any existing table. Downgrade
revokes grants (guarded) and drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4b7f21c9a06"
down_revision: Union[str, None] = "d29e6a1f4c87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RUNTIME_ROLE = "chat_ops"
RETENTION_ROLE = "chat_ops_retention"


def upgrade() -> None:
    op.create_table(
        "rag_request_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_instance_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=1), nullable=True),
        sa.Column("retrieval_outcome", sa.String(length=64), nullable=True),
        sa.Column("memory_outcome", sa.String(length=64), nullable=True),
        sa.Column("generation_outcome", sa.String(length=64), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("ebm25_latency_ms", sa.Integer(), nullable=True),
        sa.Column("rewrite_calls", sa.Integer(), nullable=True),
        sa.Column("retrieve_calls", sa.Integer(), nullable=True),
        sa.Column("rerank_calls", sa.Integer(), nullable=True),
        sa.Column("evaluate_calls", sa.Integer(), nullable=True),
        sa.Column("generate_calls", sa.Integer(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=True),
        sa.Column("history_truncated", sa.Boolean(), nullable=True),
        sa.Column("ebm25_selected_count", sa.Integer(), nullable=True),
        sa.Column("history_row_cap_reached", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_request_metrics_request_id", "rag_request_metrics", ["request_id"]
    )
    op.create_index(
        "ix_rag_request_metrics_created_at", "rag_request_metrics", ["created_at"]
    )

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
                    GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE};
                    GRANT INSERT ON rag_request_metrics TO {RUNTIME_ROLE};
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RETENTION_ROLE}') THEN
                    GRANT USAGE ON SCHEMA public TO {RETENTION_ROLE};
                    GRANT SELECT, DELETE ON rag_request_metrics TO {RETENTION_ROLE};
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
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
                    REVOKE ALL ON rag_request_metrics FROM {RUNTIME_ROLE};
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RETENTION_ROLE}') THEN
                    REVOKE ALL ON rag_request_metrics FROM {RETENTION_ROLE};
                END IF;
            END
            $$;
            """
        )
    )
    op.drop_table("rag_request_metrics")
