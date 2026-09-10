"""Initial M3 health tables migration.

Revision ID: 0001_initial_m3_tables
Revises:
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_m3_tables"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all initial Milestone 3 health tables."""
    # 1. patients table
    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_patients_user_id", "patients", ["user_id"], unique=True)

    # 2. health_profiles table
    op.create_table(
        "health_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("biological_sex", sa.String(50), nullable=True),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=True),
        sa.Column("blood_group", sa.String(10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_health_profiles_patient_id",
        "health_profiles",
        ["patient_id"],
        unique=True,
    )

    # 3. conditions table
    op.create_table(
        "conditions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column(
            "is_chronic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'PATIENT_REPORTED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conditions_patient_id", "conditions", ["patient_id"], unique=False
    )

    # 4. symptoms table
    op.create_table(
        "symptoms",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(50), nullable=True),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'PATIENT_REPORTED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_symptoms_patient_id", "symptoms", ["patient_id"], unique=False)

    # 5. medications table
    op.create_table(
        "medications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dosage", sa.String(100), nullable=True),
        sa.Column("frequency", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column(
            "as_needed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'PATIENT_REPORTED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_medications_patient_id",
        "medications",
        ["patient_id"],
        unique=False,
    )

    # 6. allergies table
    op.create_table(
        "allergies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("allergen", sa.String(255), nullable=False),
        sa.Column("reaction", sa.String(255), nullable=True),
        sa.Column("severity", sa.String(50), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'PATIENT_REPORTED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_allergies_patient_id", "allergies", ["patient_id"], unique=False
    )

    # 7. patient_goals table
    op.create_table(
        "patient_goals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_patient_goals_patient_id",
        "patient_goals",
        ["patient_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all Milestone 3 tables in reverse dependency order."""
    op.drop_index("ix_patient_goals_patient_id", table_name="patient_goals")
    op.drop_table("patient_goals")

    op.drop_index("ix_allergies_patient_id", table_name="allergies")
    op.drop_table("allergies")

    op.drop_index("ix_medications_patient_id", table_name="medications")
    op.drop_table("medications")

    op.drop_index("ix_symptoms_patient_id", table_name="symptoms")
    op.drop_table("symptoms")

    op.drop_index("ix_conditions_patient_id", table_name="conditions")
    op.drop_table("conditions")

    op.drop_index("ix_health_profiles_patient_id", table_name="health_profiles")
    op.drop_table("health_profiles")

    op.drop_index("ix_patients_user_id", table_name="patients")
    op.drop_table("patients")
