"""Add document_extractions table (M3 Slice 1).

Revision ID: 0004_add_document_extractions
Revises: 0003_provenance_integrity
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_document_extractions"
down_revision: str | Sequence[str] | None = "0003_provenance_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTRACTION_STATUS_VALUES = "('COMPLETED', 'FAILED', 'UNSUPPORTED')"
_STATUS_CONTENT_CHECK = (
    "(extraction_status = 'COMPLETED' "
    "AND extracted_text IS NOT NULL "
    "AND length(trim(extracted_text)) > 0) "
    "OR (extraction_status IN ('FAILED', 'UNSUPPORTED') "
    "AND (extracted_text IS NULL OR length(trim(extracted_text)) = 0))"
)


def upgrade() -> None:
    """Create document_extractions table with tenant integrity and semantics."""
    bind = op.get_bind()

    # 1. Enforce unique (id, patient_id) on medical_documents for composite FK
    if bind.dialect.name != "sqlite":
        op.create_unique_constraint(
            "uq_medical_documents_id_patient_id",
            "medical_documents",
            ["id", "patient_id"],
        )
    else:
        with op.batch_alter_table("medical_documents") as batch_op:
            batch_op.create_unique_constraint(
                "uq_medical_documents_id_patient_id",
                ["id", "patient_id"],
            )

    # 2. Create document_extractions table
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(50), nullable=False),
        sa.Column("extraction_method", sa.String(50), nullable=False),
        sa.Column("extraction_version", sa.String(50), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id", "patient_id"],
            ["medical_documents.id", "medical_documents.patient_id"],
            name="fk_document_extractions_document_patient",
            ondelete="CASCADE",
        ),
    )

    # 3. Create indexes
    op.create_index(
        "ix_document_extractions_document_id",
        "document_extractions",
        ["document_id"],
        unique=True,
    )
    op.create_index(
        "ix_document_extractions_patient_id",
        "document_extractions",
        ["patient_id"],
    )

    # 4. Create check constraints (non-SQLite)
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_document_extractions_extraction_status",
            "document_extractions",
            f"extraction_status IN {_EXTRACTION_STATUS_VALUES}",
        )
        op.create_check_constraint(
            "ck_document_extractions_status_content",
            "document_extractions",
            _STATUS_CONTENT_CHECK,
        )


def downgrade() -> None:
    """Drop the document_extractions table and unique constraint."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "ck_document_extractions_status_content",
            "document_extractions",
            type_="check",
        )
        op.drop_constraint(
            "ck_document_extractions_extraction_status",
            "document_extractions",
            type_="check",
        )
    op.drop_index(
        "ix_document_extractions_patient_id",
        table_name="document_extractions",
    )
    op.drop_index(
        "ix_document_extractions_document_id",
        table_name="document_extractions",
    )
    op.drop_table("document_extractions")

    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "uq_medical_documents_id_patient_id",
            "medical_documents",
            type_="unique",
        )
    else:
        with op.batch_alter_table("medical_documents") as batch_op:
            batch_op.drop_constraint(
                "uq_medical_documents_id_patient_id",
                type_="unique",
            )
