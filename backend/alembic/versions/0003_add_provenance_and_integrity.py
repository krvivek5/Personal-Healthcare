"""Add provenance and integrity columns (M6).

Revision ID: 0003_add_provenance_and_integrity
Revises: 0002_add_medical_documents
Create Date: 2026-09-11

Adds:
  - source_id (FK → medical_documents.id ON DELETE SET NULL) to clinical tables
    and patient_goals.
  - verification_state VARCHAR(50) NOT NULL to all entity tables.
  - source_type and source_id to patient_goals (source_type already existed on
    clinical tables from migration 0001, so only patient_goals gets source_type here).
  - PostgreSQL CHECK constraints enforcing canonical values on VARCHAR columns.
  - Dedicated CHECK constraints on medical_documents locking source_type and
    verification_state to 'PATIENT_REPORTED'.
  - Indexes on source_id columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_provenance_integrity"
down_revision: str | Sequence[str] | None = "0002_add_medical_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical allowed values (VARCHAR CHECK constraints)
_CLINICAL_SOURCE_TYPE_VALUES = (
    "('PATIENT_REPORTED', 'SOURCE_DOCUMENT', 'CLINICIAN_CONFIRMED')"
)
_CLINICAL_VERIFICATION_STATE_VALUES = (
    "('PATIENT_REPORTED', 'SOURCE_RECORDED', 'CLINICIAN_CONFIRMED', "
    "'AI_DERIVED', 'UNCERTAIN')"
)


def upgrade() -> None:
    """Apply M6 provenance schema changes."""

    # ── 1. conditions ────────────────────────────────────────────────────────
    op.add_column(
        "conditions",
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "conditions",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.create_index(
        "ix_conditions_source_id",
        "conditions",
        ["source_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_conditions_source_type",
            "conditions",
            f"source_type IN {_CLINICAL_SOURCE_TYPE_VALUES}",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_conditions_verification_state",
            "conditions",
            f"verification_state IN {_CLINICAL_VERIFICATION_STATE_VALUES}",
        )

    # ── 2. symptoms ──────────────────────────────────────────────────────────
    op.add_column(
        "symptoms",
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "symptoms",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.create_index(
        "ix_symptoms_source_id",
        "symptoms",
        ["source_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_symptoms_source_type",
            "symptoms",
            f"source_type IN {_CLINICAL_SOURCE_TYPE_VALUES}",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_symptoms_verification_state",
            "symptoms",
            f"verification_state IN {_CLINICAL_VERIFICATION_STATE_VALUES}",
        )

    # ── 3. medications ───────────────────────────────────────────────────────
    op.add_column(
        "medications",
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "medications",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.create_index(
        "ix_medications_source_id",
        "medications",
        ["source_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_medications_source_type",
            "medications",
            f"source_type IN {_CLINICAL_SOURCE_TYPE_VALUES}",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_medications_verification_state",
            "medications",
            f"verification_state IN {_CLINICAL_VERIFICATION_STATE_VALUES}",
        )

    # ── 4. allergies ─────────────────────────────────────────────────────────
    op.add_column(
        "allergies",
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "allergies",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.create_index(
        "ix_allergies_source_id",
        "allergies",
        ["source_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_allergies_source_type",
            "allergies",
            f"source_type IN {_CLINICAL_SOURCE_TYPE_VALUES}",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_allergies_verification_state",
            "allergies",
            f"verification_state IN {_CLINICAL_VERIFICATION_STATE_VALUES}",
        )

    # ── 5. patient_goals ─────────────────────────────────────────────────────
    # patient_goals did NOT have source_type in migration 0001 — add it now.
    op.add_column(
        "patient_goals",
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.add_column(
        "patient_goals",
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "patient_goals",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    op.create_index(
        "ix_patient_goals_source_id",
        "patient_goals",
        ["source_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_patient_goals_source_type",
            "patient_goals",
            f"source_type IN {_CLINICAL_SOURCE_TYPE_VALUES}",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_patient_goals_verification_state",
            "patient_goals",
            f"verification_state IN {_CLINICAL_VERIFICATION_STATE_VALUES}",
        )

    # ── 6. medical_documents ─────────────────────────────────────────────────
    # Add verification_state; source_type already exists (from migration 0002).
    # No source_id column on medical_documents.
    op.add_column(
        "medical_documents",
        sa.Column(
            "verification_state",
            sa.String(50),
            nullable=False,
            server_default="PATIENT_REPORTED",
        ),
    )
    # Lock source_type and verification_state to PATIENT_REPORTED on medical_documents.
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_medical_documents_source_type",
            "medical_documents",
            "source_type = 'PATIENT_REPORTED'",
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_medical_documents_verification_state",
            "medical_documents",
            "verification_state = 'PATIENT_REPORTED'",
        )

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        for table in [
            "conditions",
            "symptoms",
            "medications",
            "allergies",
            "patient_goals",
        ]:
            op.create_foreign_key(
                f"{table}_source_id_fkey",
                table,
                "medical_documents",
                ["source_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    """Reverse M6 provenance schema changes."""

    # ── medical_documents ────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "ck_medical_documents_verification_state", "medical_documents"
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_medical_documents_source_type", "medical_documents")
    op.drop_column("medical_documents", "verification_state")

    # ── patient_goals ────────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_patient_goals_verification_state", "patient_goals")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_patient_goals_source_type", "patient_goals")
    op.drop_index("ix_patient_goals_source_id", table_name="patient_goals")
    op.drop_column("patient_goals", "verification_state")
    op.drop_column("patient_goals", "source_id")
    op.drop_column("patient_goals", "source_type")

    # ── allergies ────────────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_allergies_verification_state", "allergies")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_allergies_source_type", "allergies")
    op.drop_index("ix_allergies_source_id", table_name="allergies")
    op.drop_column("allergies", "verification_state")
    op.drop_column("allergies", "source_id")

    # ── medications ──────────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_medications_verification_state", "medications")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_medications_source_type", "medications")
    op.drop_index("ix_medications_source_id", table_name="medications")
    op.drop_column("medications", "verification_state")
    op.drop_column("medications", "source_id")

    # ── symptoms ─────────────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_symptoms_verification_state", "symptoms")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_symptoms_source_type", "symptoms")
    op.drop_index("ix_symptoms_source_id", table_name="symptoms")
    op.drop_column("symptoms", "verification_state")
    op.drop_column("symptoms", "source_id")

    # ── conditions ───────────────────────────────────────────────────────────
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_conditions_verification_state", "conditions")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_conditions_source_type", "conditions")
    op.drop_index("ix_conditions_source_id", table_name="conditions")
    op.drop_column("conditions", "verification_state")
    op.drop_column("conditions", "source_id")
