import os
import tempfile
import uuid
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.db import (
    Allergy,
    Condition,
    DocumentChunk,
    HealthProfile,
    Medication,
    Patient,
    PatientGoal,
    Symptom,
)


@pytest.fixture
def migrated_db():
    """Fixture providing a temporary SQLite database with Alembic migration applied."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import pathlib

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Apply migration
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")

    # Enable SQLite foreign key enforcement for cascade and constraint testing
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    yield {"engine": engine, "cfg": cfg, "db_path": db_path}

    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_alembic_offline_sql_generation_postgresql(capsys):
    """Verify Alembic compiles valid PostgreSQL DDL with types and constraints."""
    import pathlib

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()
    sql_output = captured.out

    # Verify all tables are in the generated DDL
    expected_tables = [
        "CREATE TABLE patients",
        "CREATE TABLE health_profiles",
        "CREATE TABLE conditions",
        "CREATE TABLE symptoms",
        "CREATE TABLE medications",
        "CREATE TABLE allergies",
        "CREATE TABLE patient_goals",
        "CREATE TABLE medical_documents",
        "CREATE TABLE document_extractions",
        "CREATE TABLE document_chunks",
    ]
    for table_ddl in expected_tables:
        assert table_ddl in sql_output, f"Missing {table_ddl} in generated SQL"

    # Verify PostgreSQL UUID types
    assert "id UUID NOT NULL" in sql_output
    assert "user_id UUID NOT NULL" in sql_output
    assert "patient_id UUID NOT NULL" in sql_output

    # Verify constraints
    assert "UNIQUE (user_id)" in sql_output
    assert "UNIQUE (patient_id)" in sql_output
    assert "REFERENCES patients (id) ON DELETE CASCADE" in sql_output

    # Verify status and boolean fields
    assert "is_chronic BOOLEAN DEFAULT false NOT NULL" in sql_output
    assert "as_needed BOOLEAN DEFAULT false NOT NULL" in sql_output

    # Verify source_type defaults
    assert "source_type VARCHAR(50) DEFAULT 'PATIENT_REPORTED' NOT NULL" in sql_output
    assert (
        "verification_state VARCHAR(50) DEFAULT 'PATIENT_REPORTED' NOT NULL"
        in sql_output
    )


def test_migration_creates_expected_tables(migrated_db):
    """Verify that the Alembic migration creates all expected tables."""
    insp = inspect(migrated_db["engine"])
    tables = set(insp.get_table_names())

    expected_tables = {
        "alembic_version",
        "patients",
        "health_profiles",
        "conditions",
        "symptoms",
        "medications",
        "allergies",
        "patient_goals",
        "medical_documents",
        "document_extractions",
        "document_chunks",
    }
    assert expected_tables.issubset(tables)


def test_migration_table_columns(migrated_db):
    """Verify exact column definitions on migrated tables."""
    insp = inspect(migrated_db["engine"])

    # 1. patients columns
    patient_cols = {c["name"] for c in insp.get_columns("patients")}
    assert patient_cols == {"id", "user_id", "created_at", "updated_at"}

    # 2. health_profiles columns (verify weight_kg is NOT present)
    profile_cols = {c["name"] for c in insp.get_columns("health_profiles")}
    assert profile_cols == {
        "id",
        "patient_id",
        "date_of_birth",
        "biological_sex",
        "height_cm",
        "blood_group",
        "notes",
        "created_at",
        "updated_at",
    }
    assert "weight_kg" not in profile_cols
    assert "weight" not in profile_cols

    # 3. conditions columns
    condition_cols = {c["name"] for c in insp.get_columns("conditions")}
    assert condition_cols == {
        "id",
        "patient_id",
        "name",
        "status",
        "is_chronic",
        "started_at",
        "ended_at",
        "recorded_at",
        "notes",
        "source_id",
        "source_type",
        "verification_state",
        "created_at",
        "updated_at",
    }

    # 4. symptoms columns
    symptom_cols = {c["name"] for c in insp.get_columns("symptoms")}
    assert symptom_cols == {
        "id",
        "patient_id",
        "name",
        "severity",
        "started_at",
        "ended_at",
        "recorded_at",
        "notes",
        "source_id",
        "source_type",
        "verification_state",
        "created_at",
        "updated_at",
    }

    # 5. medications columns
    medication_cols = {c["name"] for c in insp.get_columns("medications")}
    assert medication_cols == {
        "id",
        "patient_id",
        "name",
        "dosage",
        "frequency",
        "status",
        "as_needed",
        "started_at",
        "ended_at",
        "recorded_at",
        "notes",
        "source_id",
        "source_type",
        "verification_state",
        "created_at",
        "updated_at",
    }

    # 6. allergies columns
    allergy_cols = {c["name"] for c in insp.get_columns("allergies")}
    assert allergy_cols == {
        "id",
        "patient_id",
        "allergen",
        "reaction",
        "severity",
        "recorded_at",
        "notes",
        "source_id",
        "source_type",
        "verification_state",
        "created_at",
        "updated_at",
    }

    # 7. patient_goals columns
    goal_cols = {c["name"] for c in insp.get_columns("patient_goals")}
    assert goal_cols == {
        "id",
        "patient_id",
        "description",
        "status",
        "target_date",
        "recorded_at",
        "notes",
        "source_id",
        "source_type",
        "verification_state",
        "created_at",
        "updated_at",
    }

    # 8. medical_documents columns
    document_cols = {c["name"] for c in insp.get_columns("medical_documents")}
    assert document_cols == {
        "id",
        "patient_id",
        "file_name",
        "display_name",
        "document_type",
        "content_type",
        "file_size_bytes",
        "storage_key",
        "document_date",
        "notes",
        "source_type",
        "verification_state",
        "uploaded_at",
        "created_at",
        "updated_at",
    }

    # 9. document_extractions columns (M3 restoration)
    extraction_cols = {c["name"] for c in insp.get_columns("document_extractions")}
    assert extraction_cols == {
        "id",
        "document_id",
        "patient_id",
        "extracted_text",
        "extraction_status",
        "extraction_method",
        "extraction_version",
        "extracted_at",
        "error_message",
    }


def test_foreign_key_constraints(migrated_db):
    """Verify all child tables have FK referencing patients.id with CASCADE delete."""
    insp = inspect(migrated_db["engine"])
    child_tables = [
        "health_profiles",
        "conditions",
        "symptoms",
        "medications",
        "allergies",
        "patient_goals",
        "medical_documents",
    ]

    for table in child_tables:
        fks = insp.get_foreign_keys(table)
        patient_fks = [fk for fk in fks if fk["constrained_columns"] == ["patient_id"]]
        assert len(patient_fks) == 1, f"Table {table} must have patient_id FK"
        fk = patient_fks[0]
        assert fk["referred_table"] == "patients"
        assert fk["referred_columns"] == ["id"]
        assert fk["options"].get("ondelete") == "CASCADE"


def test_migration_downgrade(migrated_db):
    """Verify that Alembic downgrade removes all domain tables cleanly."""
    cfg = migrated_db["cfg"]
    command.downgrade(cfg, "base")

    insp = inspect(migrated_db["engine"])
    tables = insp.get_table_names()
    assert "patients" not in tables
    assert "health_profiles" not in tables
    assert "conditions" not in tables
    assert "symptoms" not in tables
    assert "medications" not in tables
    assert "allergies" not in tables
    assert "patient_goals" not in tables
    assert "medical_documents" not in tables
    assert "document_extractions" not in tables
    assert "document_chunks" not in tables


def test_orm_models_metadata_and_defaults():
    """Verify ORM models metadata, unique constraints, and defaults in Python."""
    # Check patient model
    assert Patient.__tablename__ == "patients"
    assert Patient.user_id.property.columns[0].unique is True
    assert Patient.user_id.property.columns[0].nullable is False

    # Check health profile model
    assert HealthProfile.__tablename__ == "health_profiles"
    assert HealthProfile.patient_id.property.columns[0].unique is True
    assert HealthProfile.patient_id.property.columns[0].nullable is False
    assert not hasattr(HealthProfile, "weight_kg")
    assert not hasattr(HealthProfile, "weight")
    assert hasattr(HealthProfile, "height_cm")

    # Check condition model
    assert Condition.__tablename__ == "conditions"
    assert hasattr(Condition, "status")
    assert hasattr(Condition, "is_chronic")
    assert Condition.is_chronic.property.columns[0].default.arg is False
    assert Condition.source_type.property.columns[0].default.arg == "PATIENT_REPORTED"

    # Check medication model
    assert Medication.__tablename__ == "medications"
    assert hasattr(Medication, "status")
    assert hasattr(Medication, "as_needed")
    assert Medication.as_needed.property.columns[0].default.arg is False
    assert Medication.source_type.property.columns[0].default.arg == "PATIENT_REPORTED"

    # Check symptom and allergy models
    assert Symptom.source_type.property.columns[0].default.arg == "PATIENT_REPORTED"
    assert Allergy.source_type.property.columns[0].default.arg == "PATIENT_REPORTED"

    # Check relationships on Patient
    assert Patient.health_profile.property.uselist is False
    assert Patient.conditions.property.uselist is True
    assert Patient.symptoms.property.uselist is True
    assert Patient.medications.property.uselist is True
    assert Patient.allergies.property.uselist is True
    assert Patient.goals.property.uselist is True

    # Check DocumentChunk model
    assert DocumentChunk.__tablename__ == "document_chunks"
    assert DocumentChunk.chunk_index.property.columns[0].nullable is False
    assert DocumentChunk.chunk_text.property.columns[0].nullable is False
    assert DocumentChunk.embedding.property.columns[0].nullable is True
    assert DocumentChunk.page_number.property.columns[0].nullable is True


def test_unique_user_id_constraint(migrated_db):
    """Verify UNIQUE(user_id) constraint on patients table prevents duplicates."""
    engine = migrated_db["engine"]
    test_uid = uuid.uuid4()

    with Session(engine) as session:
        p1 = Patient(user_id=test_uid)
        session.add(p1)
        session.commit()

        p2 = Patient(user_id=test_uid)
        session.add(p2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_unique_patient_id_constraint_on_health_profile(migrated_db):
    """Verify UNIQUE(patient_id) constraint on health_profiles prevents duplicates."""
    engine = migrated_db["engine"]
    uid = uuid.uuid4()

    with Session(engine) as session:
        patient = Patient(user_id=uid)
        session.add(patient)
        session.commit()

        hp1 = HealthProfile(patient_id=patient.id, height_cm=Decimal("175.5"))
        session.add(hp1)
        session.commit()

        hp2 = HealthProfile(patient_id=patient.id, height_cm=Decimal("180.0"))
        session.add(hp2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_cascade_delete_on_patient(migrated_db):
    """Verify deleting a patient cascades to delete all associated health records."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.commit()

        # Add records across all tables
        profile = HealthProfile(patient_id=patient.id, biological_sex="female")
        condition = Condition(
            patient_id=patient.id,
            name="Asthma",
            status="active",
            is_chronic=True,
        )
        symptom = Symptom(patient_id=patient.id, name="Wheezing", severity="mild")
        medication = Medication(
            patient_id=patient.id,
            name="Albuterol",
            status="active",
            as_needed=True,
        )
        allergy = Allergy(patient_id=patient.id, allergen="Pollen", severity="mild")
        goal = PatientGoal(
            patient_id=patient.id,
            description="Run 5k",
            status="active",
        )

        session.add_all([profile, condition, symptom, medication, allergy, goal])
        session.commit()

        # Verify child rows exist
        assert session.query(Condition).filter_by(patient_id=patient.id).count() == 1
        assert (
            session.query(HealthProfile).filter_by(patient_id=patient.id).count() == 1
        )

        # Delete patient
        session.delete(patient)
        session.commit()

        # Verify cascade removed all child rows
        assert (
            session.query(HealthProfile).filter_by(patient_id=patient.id).count() == 0
        )
        assert session.query(Condition).filter_by(patient_id=patient.id).count() == 0
        assert session.query(Symptom).filter_by(patient_id=patient.id).count() == 0
        assert session.query(Medication).filter_by(patient_id=patient.id).count() == 0
        assert session.query(Allergy).filter_by(patient_id=patient.id).count() == 0
        assert session.query(PatientGoal).filter_by(patient_id=patient.id).count() == 0
