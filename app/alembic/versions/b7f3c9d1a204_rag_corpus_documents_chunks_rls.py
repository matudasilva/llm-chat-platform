"""RAG corpus: documents/chunks, pgvector HNSW, RLS for rag_app

Revision ID: b7f3c9d1a204
Revises: a1b2c3d4e5f6
Create Date: 2026-07-29

ORQ-21 / ADR-006. Adds the pgvector extension, `documents` and `chunks`,
an HNSW index on the embedding column, a GIN index on the application-written
tsvector column, DML-only grants to the `rag_app` role (provisioned outside
this migration — see scripts/postgres-init/10-rag-app-role.sh), and RLS
policies enforcing tenant isolation with an explicit WITH CHECK.

Grants and policies are guarded by a role-existence check so this migration
stays reversible and side-effect-free on a database where `rag_app` has not
been provisioned (e.g. a bare Postgres used only to test the migration chain
in isolation, AC5).

Downgrade drops policies, grants, indexes and tables, but never
`DROP EXTENSION vector` (other future schemas may depend on it) and never
touches the `rag_app` role (cluster-level, provisioned outside Alembic).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "b7f3c9d1a204"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("indexing_mode", sa.String(32), nullable=False, server_default="plain"),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index(
        "ux_documents_tenant_source_hash",
        "documents",
        ["tenant_id", "source_path", "content_hash", "indexing_mode"],
        unique=True,
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("context", sa.Text, nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR, nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index(
        "ux_chunks_document_ordinal", "chunks", ["document_id", "ordinal"], unique=True
    )

    # HNSW index (ADR-006 §3/§4): default m=16, ef_construction=64; shared
    # across tenants, RLS filters after the index scan at this corpus size.
    op.execute(
        sa.text(
            "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    )
    # search_vector is application-written (ADR-006 §5), not a generated
    # column, but it is still just a tsvector and takes a standard GIN index.
    op.execute(
        sa.text("CREATE INDEX ix_chunks_search_vector_gin ON chunks USING gin (search_vector)")
    )

    # DML-only grants + RLS, guarded: rag_app is provisioned by
    # scripts/postgres-init/, not by this migration (roles are cluster-level).
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO rag_app;
                    GRANT SELECT, INSERT, UPDATE, DELETE ON chunks TO rag_app;
                END IF;
            END
            $$;
            """
        )
    )

    op.execute(sa.text("ALTER TABLE documents ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE documents FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            "CREATE POLICY documents_tenant_isolation ON documents FOR ALL "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    )

    op.execute(sa.text("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE chunks FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            "CREATE POLICY chunks_tenant_isolation ON chunks FOR ALL "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS chunks_tenant_isolation ON chunks"))
    op.execute(sa.text("DROP POLICY IF EXISTS documents_tenant_isolation ON documents"))
    op.execute(sa.text("ALTER TABLE chunks DISABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE documents DISABLE ROW LEVEL SECURITY"))

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
                    REVOKE ALL ON chunks FROM rag_app;
                    REVOKE ALL ON documents FROM rag_app;
                END IF;
            END
            $$;
            """
        )
    )

    op.drop_table("chunks")
    op.drop_table("documents")
    # Deliberately not dropped: CREATE EXTENSION vector (cluster-shared,
    # other schemas may depend on it) and the rag_app role (cluster-level,
    # provisioned outside this migration chain).
