import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.db import (
    DocumentExtraction,
    MedicalDocument,
    Patient,
)
from app.schemas.document import DocumentExtractionResponse


@pytest.fixture
def migrated_db():
    """Fixture providing a temporary SQLite DB with all Alembic migrations applied."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Apply all migrations up to head (including 0004)
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")

    # Enable SQLite foreign key enforcement
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    yield {"engine": engine, "cfg": cfg, "db_path": db_path}

    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture(scope="module")
def pg_engine():
    """Live PostgreSQL engine for validating foreign keys and constraints."""
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"PostgreSQL not accessible at {url}: {e}")
    yield engine
    engine.dispose()


def test_migration_creates_document_extractions_table(migrated_db):
    """Verify migration 0004 creates document_extractions with all columns."""
    insp = inspect(migrated_db["engine"])
    tables = set(insp.get_table_names())
    assert "document_extractions" in tables

    columns = {col["name"]: col for col in insp.get_columns("document_extractions")}
    expected_column_names = {
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
    assert set(columns.keys()) == expected_column_names

    # Check nullability
    assert columns["id"]["nullable"] is False
    assert columns["document_id"]["nullable"] is False
    assert columns["patient_id"]["nullable"] is False
    assert (
        columns["extracted_text"]["nullable"] is True
    )  # nullable per M3 Slice 1 requirement
    assert columns["extraction_status"]["nullable"] is False
    assert columns["extraction_method"]["nullable"] is False
    assert columns["extraction_version"]["nullable"] is False
    assert columns["extracted_at"]["nullable"] is False
    assert columns["error_message"]["nullable"] is True


def test_migration_document_extractions_indexes(migrated_db):
    """Verify that document_id (unique) and patient_id indexes are created."""
    insp = inspect(migrated_db["engine"])
    indexes = insp.get_indexes("document_extractions")
    index_names = {idx["name"] for idx in indexes}

    assert "ix_document_extractions_document_id" in index_names
    assert "ix_document_extractions_patient_id" in index_names

    for idx in indexes:
        if idx["name"] == "ix_document_extractions_document_id":
            assert idx["unique"] == 1 or idx["unique"] is True
            assert idx["column_names"] == ["document_id"]
        elif idx["name"] == "ix_document_extractions_patient_id":
            assert idx["column_names"] == ["patient_id"]


def test_migration_downgrade_and_upgrade(migrated_db):
    """Verify that migration 0004 can be downgraded and re-upgraded cleanly."""
    cfg = migrated_db["cfg"]
    engine = migrated_db["engine"]

    # Downgrade to 0003
    command.downgrade(cfg, "0003_provenance_integrity")
    insp = inspect(engine)
    assert "document_extractions" not in insp.get_table_names()

    # Re-upgrade to head
    command.upgrade(cfg, "head")
    insp = inspect(engine)
    assert "document_extractions" in insp.get_table_names()


def test_orm_document_extraction_one_to_one_relationship(migrated_db):
    """Verify one-to-one relationship between MedicalDocument and DocumentExtraction."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        # Create Patient
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.flush()

        # Create MedicalDocument
        now_dt = datetime.now(timezone.utc)
        doc = MedicalDocument(
            patient_id=patient.id,
            file_name="lab_report.pdf",
            display_name="Metabolic Panel",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1024,
            storage_key=f"documents/{patient.id}/{uuid.uuid4()}",
            source_type="PATIENT_REPORTED",
            verification_state="PATIENT_REPORTED",
            uploaded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(doc)
        session.flush()

        # Create DocumentExtraction
        extraction = DocumentExtraction(
            document_id=doc.id,
            patient_id=patient.id,
            extracted_text="Sodium: 140 mEq/L\nPotassium: 4.2 mEq/L",
            extraction_status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now_dt,
        )
        session.add(extraction)
        session.commit()

        # Verify relationship from doc to extraction
        session.refresh(doc)
        assert doc.document_extraction is not None
        assert doc.document_extraction.id == extraction.id
        expected_text = "Sodium: 140 mEq/L\nPotassium: 4.2 mEq/L"
        assert doc.document_extraction.extracted_text == expected_text
        assert doc.document_extraction.extraction_status == "COMPLETED"
        assert doc.document_extraction.extraction_method == "pypdf"
        assert doc.document_extraction.extraction_version == "1.0.0"
        assert doc.document_extraction.document.id == doc.id

        # Verify cascade delete on document deletion
        session.delete(doc)
        session.commit()

        # Extraction should be deleted automatically via ON DELETE CASCADE
        remaining_extractions = (
            session.query(DocumentExtraction)
            .filter(DocumentExtraction.id == extraction.id)
            .all()
        )
        assert len(remaining_extractions) == 0


def test_tenant_integrity_mismatched_patient_id_rejected(pg_engine):
    """
    TENANT INTEGRITY: Prove that a mismatched patient_id CANNOT be persisted.
    If document_extractions.patient_id != medical_documents.patient_id,
    PostgreSQL composite foreign key (or model validator) MUST reject persistence.
    """
    with Session(pg_engine) as session:
        # Create Patient A and Patient B
        patient_a = Patient(user_id=uuid.uuid4())
        patient_b = Patient(user_id=uuid.uuid4())
        session.add_all([patient_a, patient_b])
        session.flush()

        # Create document belonging to Patient A
        now_dt = datetime.now(timezone.utc)
        doc_a = MedicalDocument(
            patient_id=patient_a.id,
            file_name="blood_test.pdf",
            display_name="Blood Test",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=2048,
            storage_key=f"documents/{patient_a.id}/{uuid.uuid4()}",
            source_type="PATIENT_REPORTED",
            verification_state="PATIENT_REPORTED",
            uploaded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(doc_a)
        session.commit()

        # Attempt extraction pointing to doc_a.id but patient_b.id (mismatch!)
        with pytest.raises((IntegrityError, ValueError)):
            # Direct SQL or model insertion with mismatched patient_id
            mismatched_extraction = DocumentExtraction(
                document_id=doc_a.id,
                patient_id=patient_b.id,  # MISMATCH
                extracted_text="Some extracted data",
                extraction_status="COMPLETED",
                extraction_method="pypdf",
                extraction_version="1.0.0",
                extracted_at=now_dt,
            )
            session.add(mismatched_extraction)
            session.flush()

        session.rollback()

        # Matching patient_id MUST succeed and persist
        matching_extraction = DocumentExtraction(
            document_id=doc_a.id,
            patient_id=patient_a.id,  # MATCH
            extracted_text="Some extracted data",
            extraction_status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now_dt,
        )
        session.add(matching_extraction)
        session.commit()

        persisted = (
            session.query(DocumentExtraction)
            .filter(DocumentExtraction.id == matching_extraction.id)
            .one()
        )
        assert persisted.patient_id == patient_a.id
        assert persisted.document_id == doc_a.id

        # Clean up
        session.delete(doc_a)
        session.delete(patient_a)
        session.delete(patient_b)
        session.commit()


def test_extraction_content_semantics_lifecycle(pg_engine):
    """
    EXTRACTION CONTENT SEMANTICS:
    - COMPLETED requires non-empty extracted_text
    - FAILED / UNSUPPORTED permits null/empty text, but rejects non-empty text
    """
    with Session(pg_engine) as session:
        patient = Patient(user_id=uuid.uuid4())
        session.add(patient)
        session.flush()

        now_dt = datetime.now(timezone.utc)

        def make_doc(name: str) -> MedicalDocument:
            doc = MedicalDocument(
                patient_id=patient.id,
                file_name=name,
                display_name=name,
                document_type="lab_report",
                content_type="application/pdf",
                file_size_bytes=1024,
                storage_key=f"documents/{patient.id}/{uuid.uuid4()}",
                source_type="PATIENT_REPORTED",
                verification_state="PATIENT_REPORTED",
                uploaded_at=now_dt,
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(doc)
            session.flush()
            return doc

        # 1. COMPLETED with valid text -> succeeds
        doc1 = make_doc("doc1.pdf")
        ext1 = DocumentExtraction(
            document_id=doc1.id,
            patient_id=patient.id,
            extracted_text="Valid clinical findings",
            extraction_status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now_dt,
        )
        session.add(ext1)
        session.commit()
        assert ext1.id is not None

        # 2. COMPLETED with None -> rejected
        doc2 = make_doc("doc2.pdf")
        with pytest.raises((IntegrityError, ValueError)):
            ext2 = DocumentExtraction(
                document_id=doc2.id,
                patient_id=patient.id,
                extracted_text=None,
                extraction_status="COMPLETED",
                extraction_method="pypdf",
                extraction_version="1.0.0",
                extracted_at=now_dt,
            )
            session.add(ext2)
            session.commit()
        session.rollback()

        # 3. COMPLETED with empty/whitespace text -> rejected
        doc3 = make_doc("doc3.pdf")
        with pytest.raises((IntegrityError, ValueError)):
            ext3 = DocumentExtraction(
                document_id=doc3.id,
                patient_id=patient.id,
                extracted_text="   ",
                extraction_status="COMPLETED",
                extraction_method="pypdf",
                extraction_version="1.0.0",
                extracted_at=now_dt,
            )
            session.add(ext3)
            session.commit()
        session.rollback()

        # 4. FAILED with None -> succeeds
        doc4 = make_doc("doc4.pdf")
        ext4 = DocumentExtraction(
            document_id=doc4.id,
            patient_id=patient.id,
            extracted_text=None,
            extraction_status="FAILED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now_dt,
            error_message="Corrupted PDF syntax",
        )
        session.add(ext4)
        session.commit()
        assert ext4.id is not None
        assert ext4.extracted_text is None
        assert ext4.error_message == "Corrupted PDF syntax"

        # 5. FAILED with non-empty text -> rejected
        doc5 = make_doc("doc5.pdf")
        with pytest.raises((IntegrityError, ValueError)):
            ext5 = DocumentExtraction(
                document_id=doc5.id,
                patient_id=patient.id,
                extracted_text="Usable extracted text should not exist on failure",
                extraction_status="FAILED",
                extraction_method="pypdf",
                extraction_version="1.0.0",
                extracted_at=now_dt,
                error_message="Error",
            )
            session.add(ext5)
            session.commit()
        session.rollback()

        # 6. UNSUPPORTED with None -> succeeds
        doc6 = make_doc("doc6.pdf")
        ext6 = DocumentExtraction(
            document_id=doc6.id,
            patient_id=patient.id,
            extracted_text=None,
            extraction_status="UNSUPPORTED",
            extraction_method="unsupported",
            extraction_version="1.0.0",
            extracted_at=now_dt,
            error_message="MIME type audio/mpeg not supported",
        )
        session.add(ext6)
        session.commit()
        assert ext6.id is not None

        # 7. UNSUPPORTED with non-empty text -> rejected
        doc7 = make_doc("doc7.pdf")
        with pytest.raises((IntegrityError, ValueError)):
            ext7 = DocumentExtraction(
                document_id=doc7.id,
                patient_id=patient.id,
                extracted_text="Extracted text on unsupported",
                extraction_status="UNSUPPORTED",
                extraction_method="unsupported",
                extraction_version="1.0.0",
                extracted_at=now_dt,
            )
            session.add(ext7)
            session.commit()
        session.rollback()

        # Clean up
        session.delete(patient)
        session.commit()


def test_pydantic_document_extraction_lifecycle_semantics():
    """Verify DocumentExtractionResponse enforces extraction_status semantics."""
    doc_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    ext_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. COMPLETED with valid text -> valid
    resp = DocumentExtractionResponse(
        id=ext_id,
        document_id=doc_id,
        patient_id=patient_id,
        extracted_text="Sample valid text",
        extraction_status="COMPLETED",
        extraction_method="pypdf",
        extraction_version="1.0.0",
        extracted_at=now,
    )
    assert resp.extracted_text == "Sample valid text"

    # 2. COMPLETED with None -> ValidationError
    with pytest.raises(ValidationError):
        DocumentExtractionResponse(
            id=ext_id,
            document_id=doc_id,
            patient_id=patient_id,
            extracted_text=None,
            extraction_status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now,
        )

    # 3. COMPLETED with whitespace -> ValidationError
    with pytest.raises(ValidationError):
        DocumentExtractionResponse(
            id=ext_id,
            document_id=doc_id,
            patient_id=patient_id,
            extracted_text="   ",
            extraction_status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now,
        )

    # 4. FAILED with None -> valid
    resp_failed = DocumentExtractionResponse(
        id=ext_id,
        document_id=doc_id,
        patient_id=patient_id,
        extracted_text=None,
        extraction_status="FAILED",
        extraction_method="pypdf",
        extraction_version="1.0.0",
        extracted_at=now,
        error_message="Parsing error",
    )
    assert resp_failed.extracted_text is None

    # 5. FAILED with non-empty text -> ValidationError
    with pytest.raises(ValidationError):
        DocumentExtractionResponse(
            id=ext_id,
            document_id=doc_id,
            patient_id=patient_id,
            extracted_text="Text should not exist",
            extraction_status="FAILED",
            extraction_method="pypdf",
            extraction_version="1.0.0",
            extracted_at=now,
        )

    # 6. UNSUPPORTED with None -> valid
    resp_unsupported = DocumentExtractionResponse(
        id=ext_id,
        document_id=doc_id,
        patient_id=patient_id,
        extracted_text=None,
        extraction_status="UNSUPPORTED",
        extraction_method="unsupported",
        extraction_version="1.0.0",
        extracted_at=now,
    )
    assert resp_unsupported.extracted_text is None

    # 7. UNSUPPORTED with non-empty text -> ValidationError
    with pytest.raises(ValidationError):
        DocumentExtractionResponse(
            id=ext_id,
            document_id=doc_id,
            patient_id=patient_id,
            extracted_text="Text should not exist",
            extraction_status="UNSUPPORTED",
            extraction_method="unsupported",
            extraction_version="1.0.0",
            extracted_at=now,
        )
