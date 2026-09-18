"""Add document_chunks table (M4 Slice 1).

Revision ID: 0005_add_document_chunks
Revises: 0004_add_document_extractions
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_add_document_chunks"
down_revision: str | Sequence[str] | None = "0004_add_document_extractions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document_chunks table with vector extension, HNSW, and constraints."""
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    # 1. Enable pgvector extension (PostgreSQL only)
    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Determine embedding column type based on dialect
    if is_postgresql:
        # Import here to avoid compile-time errors on SQLite environments
        from pgvector.sqlalchemy import Vector as PGVector

        embedding_col = sa.Column(
            "embedding",
            PGVector(768),
            nullable=True,
        )
    else:
        # SQLite fallback: store as TEXT for structural compatibility
        embedding_col = sa.Column(
            "embedding",
            sa.Text(),
            nullable=True,
        )

    # 3. Create document_chunks table
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("patient_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        embedding_col,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Composite tenant foreign key: (document_id, patient_id) -> medical_documents
        sa.ForeignKeyConstraint(
            ["document_id", "patient_id"],
            ["medical_documents.id", "medical_documents.patient_id"],
            name="fk_document_chunks_document_patient",
            ondelete="CASCADE",
        ),
        # Unique constraint on (document_id, chunk_index)
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_chunk_index",
        ),
        # Non-empty text check constraint
        sa.CheckConstraint(
            "length(trim(chunk_text)) > 0",
            name="ck_document_chunks_non_empty_text",
        ),
    )

    # 4. B-tree index on (patient_id, document_id) for tenant-scoped queries
    op.create_index(
        "ix_document_chunks_patient_document",
        "document_chunks",
        ["patient_id", "document_id"],
    )

    # 5. Individual column indexes for join performance
    op.create_index(
        "ix_document_chunks_document_id",
        "document_chunks",
        ["document_id"],
    )
    op.create_index(
        "ix_document_chunks_patient_id",
        "document_chunks",
        ["patient_id"],
    )

    # 6. HNSW vector index (PostgreSQL only — requires pgvector)
    if is_postgresql:
        op.create_index(
            "ix_document_chunks_embedding_hnsw",
            "document_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    """Drop the document_chunks table, indexes, and vector extension."""
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    # 1. Drop HNSW vector index first (PostgreSQL only)
    if is_postgresql:
        op.drop_index(
            "ix_document_chunks_embedding_hnsw",
            table_name="document_chunks",
        )

    # 2. Drop B-tree and column indexes
    op.drop_index(
        "ix_document_chunks_patient_id",
        table_name="document_chunks",
    )
    op.drop_index(
        "ix_document_chunks_document_id",
        table_name="document_chunks",
    )
    op.drop_index(
        "ix_document_chunks_patient_document",
        table_name="document_chunks",
    )

    # 3. Drop table (cascades unique/check constraints and FK)
    op.drop_table("document_chunks")

    # 4. Drop vector extension (PostgreSQL only — migration 0005 introduced it)
    if is_postgresql:
        op.execute("DROP EXTENSION IF EXISTS vector;")
