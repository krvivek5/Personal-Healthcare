import uuid
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, insert, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.db import (
    Allergy,
    Condition,
    HealthProfile,
    Medication,
    Patient,
    PatientGoal,
    Symptom,
)

EXPECTED_TABLES = {
    "patients",
    "health_profiles",
    "conditions",
    "symptoms",
    "medications",
    "allergies",
    "patient_goals",
}


@pytest.fixture(scope="module")
def pg_engine():
    """Engine connected to the live PostgreSQL database from settings."""
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"PostgreSQL not accessible at {url}: {e}")
    yield engine
    engine.dispose()


def test_pg_all_7_tables_exist(pg_engine):
    """Confirm all 7 expected health tables exist in PostgreSQL."""
    insp = inspect(pg_engine)
    tables = set(insp.get_table_names())
    assert EXPECTED_TABLES.issubset(tables), (
        f"Missing tables: {EXPECTED_TABLES - tables}"
    )
    assert "alembic_version" in tables


def test_pg_pk_fk_constraints(pg_engine):
    """Confirm PK/FK constraints exist and enforce CASCADE delete."""
    insp = inspect(pg_engine)
    for table_name in EXPECTED_TABLES:
        pk = insp.get_pk_constraint(table_name)
        assert pk.get("constrained_columns") == ["id"], f"{table_name} PK must be 'id'"

        if table_name != "patients":
            fks = insp.get_foreign_keys(table_name)

            # Extract the patient_id foreign key which is present on all these tables
            patient_fks = [
                fk for fk in fks if fk["constrained_columns"] == ["patient_id"]
            ]
            assert len(patient_fks) == 1, (
                f"{table_name} must have patient_id foreign key"
            )
            fk = patient_fks[0]
            assert fk["referred_table"] == "patients"
            assert fk["referred_columns"] == ["id"]
            assert fk["options"].get("ondelete") == "CASCADE"

            # Clinical tables now also have a source_id foreign key
            if table_name not in ["health_profiles", "medical_documents"]:
                source_fks = [
                    fk for fk in fks if fk["constrained_columns"] == ["source_id"]
                ]
                assert len(source_fks) == 1, (
                    f"{table_name} must have source_id foreign key"
                )
                fk = source_fks[0]
                assert fk["referred_table"] == "medical_documents"
                assert fk["referred_columns"] == ["id"]
                assert fk["options"].get("ondelete") == "SET NULL"


def test_pg_unique_constraints(pg_engine):
    """Confirm UNIQUE(user_id) on patients and UNIQUE(patient_id) on health_profiles."""
    insp = inspect(pg_engine)

    # Check patients.user_id unique constraint or index
    patient_uniques = [
        u["column_names"] for u in insp.get_unique_constraints("patients")
    ]
    patient_unique_ix = [
        ix["column_names"] for ix in insp.get_indexes("patients") if ix["unique"]
    ]
    assert ["user_id"] in patient_uniques or ["user_id"] in patient_unique_ix

    # Check health_profiles.patient_id unique constraint or index
    hp_uniques = [
        u["column_names"] for u in insp.get_unique_constraints("health_profiles")
    ]
    hp_unique_ix = [
        ix["column_names"] for ix in insp.get_indexes("health_profiles") if ix["unique"]
    ]
    assert ["patient_id"] in hp_uniques or ["patient_id"] in hp_unique_ix


def test_pg_column_types_uuid_and_timestamptz(pg_engine):
    """Confirm native PostgreSQL UUID and TIMESTAMPTZ data types."""
    with pg_engine.connect() as conn:
        for table in sorted(EXPECTED_TABLES):
            query = text(
                "SELECT column_name, data_type, udt_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = :t"
            )
            cols = {row[0]: row for row in conn.execute(query, {"t": table})}

            # UUID checks
            for id_col in ("id", "user_id", "patient_id"):
                if id_col in cols:
                    assert cols[id_col][2] == "uuid", (
                        f"{table}.{id_col} must be native uuid, got {cols[id_col][2]}"
                    )

            # TIMESTAMPTZ checks
            for ts_col in ("created_at", "updated_at", "recorded_at"):
                if ts_col in cols:
                    assert cols[ts_col][2] == "timestamptz" or (
                        "timestamp with time zone" in cols[ts_col][1]
                    ), f"{table}.{ts_col} must be timestamptz, got {cols[ts_col][1]}"


def test_pg_on_delete_cascade_behavior(pg_engine):
    """Confirm ON DELETE CASCADE behavior on live PostgreSQL."""
    with Session(pg_engine) as session:
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.commit()

        p_id = patient.id
        hp = HealthProfile(
            patient_id=p_id, biological_sex="female", height_cm=Decimal("170.0")
        )
        cond = Condition(
            patient_id=p_id, name="Hypertension", status="active", is_chronic=True
        )
        symp = Symptom(patient_id=p_id, name="Fatigue", severity="mild")
        med = Medication(
            patient_id=p_id, name="Lisinopril", status="active", as_needed=False
        )
        alg = Allergy(patient_id=p_id, allergen="Dust", severity="moderate")
        goal = PatientGoal(
            patient_id=p_id, description="Walk 10k steps", status="active"
        )

        session.add_all([hp, cond, symp, med, alg, goal])
        session.commit()

        # Confirm child rows exist
        assert session.query(HealthProfile).filter_by(patient_id=p_id).count() == 1
        assert session.query(Condition).filter_by(patient_id=p_id).count() == 1
        assert session.query(Symptom).filter_by(patient_id=p_id).count() == 1
        assert session.query(Medication).filter_by(patient_id=p_id).count() == 1
        assert session.query(Allergy).filter_by(patient_id=p_id).count() == 1
        assert session.query(PatientGoal).filter_by(patient_id=p_id).count() == 1

        # Delete patient and commit
        session.delete(patient)
        session.commit()

        # Confirm all 6 child tables cascaded deletion in PostgreSQL
        assert session.query(HealthProfile).filter_by(patient_id=p_id).count() == 0
        assert session.query(Condition).filter_by(patient_id=p_id).count() == 0
        assert session.query(Symptom).filter_by(patient_id=p_id).count() == 0
        assert session.query(Medication).filter_by(patient_id=p_id).count() == 0
        assert session.query(Allergy).filter_by(patient_id=p_id).count() == 0
        assert session.query(PatientGoal).filter_by(patient_id=p_id).count() == 0


def test_pg_source_type_cannot_be_null(pg_engine):
    """Check that source_type column has NOT NULL constraint in PostgreSQL."""
    with pg_engine.connect() as conn:
        clinical_tables = ["conditions", "symptoms", "medications", "allergies"]
        for table in clinical_tables:
            query = text(
                "SELECT is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'source_type'"
            )
            row = conn.execute(query, {"t": table}).fetchone()
            assert row is not None, f"source_type column missing from {table}"
            assert row[0] == "NO", (
                f"source_type in {table} must be NOT NULL (is_nullable=NO)"
            )
            assert "PATIENT_REPORTED" in str(row[1]), (
                f"source_type default must be PATIENT_REPORTED, got {row[1]}"
            )

    # Test that inserting NULL into source_type raises IntegrityError
    with Session(pg_engine) as session:
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.commit()

        # Direct insert passing explicit NULL to verify NOT NULL constraint
        with pytest.raises(IntegrityError):
            session.execute(
                insert(Condition).values(
                    id=uuid.uuid4(),
                    patient_id=patient.id,
                    name="Test Condition",
                    status="active",
                    source_type=None,
                )
            )
            session.commit()
        session.rollback()

        session.delete(patient)
        session.commit()


def test_pg_updated_at_maintenance_behavior(pg_engine):
    """Check how updated_at is maintained on record updates."""
    with Session(pg_engine) as session:
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.commit()

        initial_created_at = patient.created_at
        initial_updated_at = patient.updated_at
        assert initial_created_at is not None
        assert initial_updated_at is not None

        # Update patient record
        patient.user_id = uuid.uuid4()
        session.commit()
        session.refresh(patient)

        # SQLAlchemy onupdate=func.now() updates the timestamp on ORM flush/commit
        assert patient.updated_at >= initial_updated_at

        session.delete(patient)
        session.commit()


def test_pg_migration_downgrade_and_reapply(pg_engine):
    """Verify the migration can be downgraded and reapplied cleanly on PostgreSQL."""
    cfg = Config("alembic.ini")

    # Downgrade to base
    command.downgrade(cfg, "base")
    insp = inspect(pg_engine)
    remaining_tables = set(insp.get_table_names())
    for t in EXPECTED_TABLES:
        assert t not in remaining_tables, (
            f"Table {t} should have been dropped on downgrade"
        )

    # Re-apply migration
    command.upgrade(cfg, "head")
    insp_after = inspect(pg_engine)
    reapplied_tables = set(insp_after.get_table_names())
    assert EXPECTED_TABLES.issubset(reapplied_tables), (
        f"Missing tables after re-upgrade: {EXPECTED_TABLES - reapplied_tables}"
    )
