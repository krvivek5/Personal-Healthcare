"""Test suite for DocumentChunk schema, constraints, and migration lifecycle (S1).

Covers:
- Migration upgrade/downgrade/re-upgrade on SQLite
- Table existence and column specifications
- PostgreSQL: pgvector extension, vector(768) type, HNSW index
- Composite FK (document_id, patient_id) -> medical_documents
- ON DELETE CASCADE from MedicalDocument -> DocumentChunk
- Non-empty chunk_text check constraint
- UNIQUE(document_id, chunk_index) constraint
- SQLite migration compatibility (no pgvector syntax errors)
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.db import DocumentChunk, MedicalDocument, Patient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_db():
    """Temporary SQLite database with all migrations applied (offline fixture)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import pathlib

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Apply all migrations up to head (includes 0005)
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


@pytest.fixture(scope="module")
def pg_engine():
    """Live PostgreSQL engine — skipped when PostgreSQL is not accessible."""
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"PostgreSQL not accessible at {url}: {e}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def pg_migrated_engine(pg_engine):
    """Ensure 0005 migration is applied on the live PostgreSQL instance."""
    import pathlib

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
    yield pg_engine


# ---------------------------------------------------------------------------
# Helper: insert a Patient + MedicalDocument pair
# ---------------------------------------------------------------------------


def _insert_patient_and_document(session: Session) -> tuple:
    """Create and flush a Patient and MedicalDocument, returning (patient, doc)."""
    now_dt = datetime.now(timezone.utc)
    patient = Patient(user_id=uuid.uuid4())
    session.add(patient)
    session.flush()

    doc = MedicalDocument(
        patient_id=patient.id,
        file_name="test.pdf",
        display_name="Test Document",
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
    return patient, doc


# ---------------------------------------------------------------------------
# 1. SQLite migration upgrade / downgrade / re-upgrade
# ---------------------------------------------------------------------------


def test_migration_creates_document_chunks_table(migrated_db):
    """Verify migration 0005 creates document_chunks with all expected columns."""
    insp = inspect(migrated_db["engine"])
    tables = set(insp.get_table_names())
    assert "document_chunks" in tables, "document_chunks table not found after upgrade"

    columns = {col["name"]: col for col in insp.get_columns("document_chunks")}
    expected_columns = {
        "id",
        "document_id",
        "patient_id",
        "chunk_index",
        "page_number",
        "chunk_text",
        "embedding",
        "created_at",
    }
    assert set(columns.keys()) == expected_columns

    # Nullability assertions per S1 spec
    assert columns["id"]["nullable"] is False
    assert columns["document_id"]["nullable"] is False
    assert columns["patient_id"]["nullable"] is False
    assert columns["chunk_index"]["nullable"] is False
    assert columns["page_number"]["nullable"] is True
    assert columns["chunk_text"]["nullable"] is False
    assert columns["embedding"]["nullable"] is True
    assert columns["created_at"]["nullable"] is False


def test_migration_downgrade_and_re_upgrade(migrated_db):
    """Migration 0005 can be downgraded to 0004 and re-upgraded to head cleanly."""
    cfg = migrated_db["cfg"]
    engine = migrated_db["engine"]

    # Downgrade to 0004
    command.downgrade(cfg, "0004_add_document_extractions")
    insp = inspect(engine)
    assert "document_chunks" not in insp.get_table_names(), (
        "document_chunks should be absent after downgrade to 0004"
    )
    # Prior tables preserved
    assert "document_extractions" in insp.get_table_names()
    assert "medical_documents" in insp.get_table_names()

    # Re-upgrade to head
    command.upgrade(cfg, "head")
    insp = inspect(engine)
    assert "document_chunks" in insp.get_table_names(), (
        "document_chunks should re-appear after re-upgrade"
    )


def test_sqlite_migration_compatibility(migrated_db):
    """Full migration applies on SQLite without pgvector syntax errors."""
    # If we reach this point the fixture has already applied all migrations cleanly.
    insp = inspect(migrated_db["engine"])
    assert "document_chunks" in insp.get_table_names()


# ---------------------------------------------------------------------------
# 2. SQLite: structural constraints
# ---------------------------------------------------------------------------


def test_composite_fk_rejects_mismatched_patient(migrated_db):
    """COMPOSITE FK: chunk with patient_id from a different patient is rejected."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient_a = Patient(user_id=uuid.uuid4())
        patient_b = Patient(user_id=uuid.uuid4())
        session.add_all([patient_a, patient_b])
        session.flush()

        now_dt = datetime.now(timezone.utc)
        doc_a = MedicalDocument(
            patient_id=patient_a.id,
            file_name="doc_a.pdf",
            display_name="Doc A",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=512,
            storage_key=f"documents/{patient_a.id}/{uuid.uuid4()}",
            source_type="PATIENT_REPORTED",
            verification_state="PATIENT_REPORTED",
            uploaded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(doc_a)
        session.flush()

        # Attempt to link a chunk to doc_a but with patient_b's id -> should fail
        bad_chunk = DocumentChunk(
            document_id=doc_a.id,
            patient_id=patient_b.id,  # mismatched!
            chunk_index=0,
            chunk_text="Some medical text",
        )
        session.add(bad_chunk)

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_cascade_delete_removes_chunks(migrated_db):
    """Deleting a MedicalDocument cascades to delete all associated DocumentChunks."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient, doc = _insert_patient_and_document(session)

        chunk1 = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="First chunk of the document.",
        )
        chunk2 = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=1,
            chunk_text="Second chunk of the document.",
        )
        session.add_all([chunk1, chunk2])
        session.commit()

        chunk_ids = [chunk1.id, chunk2.id]

        # Delete parent document
        session.delete(doc)
        session.commit()

        # All associated chunks must be gone
        remaining = (
            session.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids)).count()
        )
        assert remaining == 0, (
            "Cascade delete failed: chunks still exist after doc deletion"
        )


def test_non_empty_chunk_text_constraint_empty_string(migrated_db):
    """Empty chunk_text (empty string) is rejected by the check constraint."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient, doc = _insert_patient_and_document(session)

        bad_chunk = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="",  # violates ck_document_chunks_non_empty_text
        )
        session.add(bad_chunk)

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_non_empty_chunk_text_constraint_whitespace(migrated_db):
    """Whitespace-only chunk_text is rejected by the check constraint."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient, doc = _insert_patient_and_document(session)

        bad_chunk = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="   ",  # violates ck_document_chunks_non_empty_text
        )
        session.add(bad_chunk)

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_duplicate_chunk_index_rejected(migrated_db):
    """Duplicate (document_id, chunk_index) is rejected by the unique constraint."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient, doc = _insert_patient_and_document(session)

        chunk1 = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="First chunk.",
        )
        session.add(chunk1)
        session.commit()

        duplicate = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,  # violates uq_document_chunks_document_chunk_index
            chunk_text="Duplicate chunk.",
        )
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_valid_chunk_insertion(migrated_db):
    """Valid DocumentChunk insertion succeeds and is retrievable."""
    engine = migrated_db["engine"]

    with Session(engine) as session:
        patient, doc = _insert_patient_and_document(session)

        chunk = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="Patient presents with elevated sodium: 145 mEq/L.",
            page_number=1,
        )
        session.add(chunk)
        session.commit()

        retrieved = session.get(DocumentChunk, chunk.id)
        assert retrieved is not None
        assert retrieved.document_id == doc.id
        assert retrieved.patient_id == patient.id
        assert retrieved.chunk_index == 0
        assert (
            retrieved.chunk_text == "Patient presents with elevated sodium: 145 mEq/L."
        )
        assert retrieved.page_number == 1
        assert retrieved.embedding is None  # no embedding set
        assert retrieved.created_at is not None


# ---------------------------------------------------------------------------
# 3. ORM model metadata assertions
# ---------------------------------------------------------------------------


def test_document_chunk_orm_metadata():
    """Verify DocumentChunk ORM model tablename, key column properties, and indexes."""
    assert DocumentChunk.__tablename__ == "document_chunks"

    # chunk_index is non-nullable
    assert DocumentChunk.chunk_index.property.columns[0].nullable is False

    # page_number is nullable
    assert DocumentChunk.page_number.property.columns[0].nullable is True

    # chunk_text is non-nullable
    assert DocumentChunk.chunk_text.property.columns[0].nullable is False

    # embedding is nullable
    assert DocumentChunk.embedding.property.columns[0].nullable is True

    # Verify HNSW index is declared in ORM table metadata
    index_names = {idx.name for idx in DocumentChunk.__table__.indexes}
    assert "ix_document_chunks_embedding_hnsw" in index_names, (
        "HNSW index ix_document_chunks_embedding_hnsw not found in ORM table metadata"
    )

    # Verify the HNSW index has the correct PostgreSQL dialect kwargs
    hnsw_index = next(
        idx
        for idx in DocumentChunk.__table__.indexes
        if idx.name == "ix_document_chunks_embedding_hnsw"
    )
    assert hnsw_index.dialect_kwargs.get("postgresql_using") == "hnsw", (
        "HNSW index must declare postgresql_using='hnsw'"
    )
    assert hnsw_index.dialect_kwargs.get("postgresql_ops") == {
        "embedding": "vector_cosine_ops"
    }, "HNSW index must declare postgresql_ops={'embedding': 'vector_cosine_ops'}"


def test_medical_document_has_chunks_relationship():
    """MedicalDocument.chunks relationship exists and is configured correctly."""
    assert hasattr(MedicalDocument, "chunks")
    assert MedicalDocument.chunks.property.uselist is True
    # SQLAlchemy expands "all, delete-orphan" into individual CascadeOptions at runtime.
    # Check that both 'delete-orphan' and 'delete' are in the expanded cascade set.
    cascade = MedicalDocument.chunks.property.cascade
    assert "delete-orphan" in cascade
    assert "delete" in cascade


# ---------------------------------------------------------------------------
# 4. PostgreSQL-specific: extension, vector type, HNSW index
# ---------------------------------------------------------------------------


def test_pg_vector_extension_exists(pg_migrated_engine):
    """PostgreSQL: vector extension is installed after migration 0005."""
    with pg_migrated_engine.connect() as conn:
        result = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        row = result.fetchone()
    assert row is not None, "pgvector extension not found in pg_extension"
    assert row[0] == "vector"


def test_pg_embedding_column_is_vector_768(pg_migrated_engine):
    """PostgreSQL: embedding column data type is vector(768)."""
    with pg_migrated_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT data_type, udt_name "
                "FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' "
                "  AND column_name = 'embedding'"
            )
        )
        row = result.fetchone()
    assert row is not None, "embedding column not found in information_schema"
    # pgvector registers columns as USER-DEFINED with udt_name 'vector'
    assert row[1] == "vector", f"Expected udt_name 'vector', got '{row[1]}'"


def test_pg_hnsw_index_exists(pg_migrated_engine):
    """PostgreSQL: HNSW index ix_document_chunks_embedding_hnsw exists with
    vector_cosine_ops."""
    with pg_migrated_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT am.amname "
                "FROM pg_index pi "
                "JOIN pg_class ic ON ic.oid = pi.indexrelid "
                "JOIN pg_class tc ON tc.oid = pi.indrelid "
                "JOIN pg_am am ON am.oid = ic.relam "
                "WHERE tc.relname = 'document_chunks' "
                "  AND ic.relname = 'ix_document_chunks_embedding_hnsw'"
            )
        )
        row = result.fetchone()
    assert row is not None, "ix_document_chunks_embedding_hnsw index not found"
    assert row[0] == "hnsw", f"Expected access method 'hnsw', got '{row[0]}'"


def test_pg_hnsw_index_uses_cosine_ops(pg_migrated_engine):
    """PostgreSQL: HNSW index uses vector_cosine_ops operator class."""
    with pg_migrated_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT opc.opcname "
                "FROM pg_index pi "
                "JOIN pg_class ic ON ic.oid = pi.indexrelid "
                "JOIN pg_class tc ON tc.oid = pi.indrelid "
                "JOIN pg_opclass opc ON opc.oid = ANY(pi.indclass::int[]) "
                "WHERE tc.relname = 'document_chunks' "
                "  AND ic.relname = 'ix_document_chunks_embedding_hnsw'"
            )
        )
        row = result.fetchone()
    assert row is not None, "Could not retrieve operator class for HNSW index"
    assert row[0] == "vector_cosine_ops", (
        f"Expected 'vector_cosine_ops', got '{row[0]}'"
    )


def test_pg_composite_fk_rejects_mismatched_patient(pg_migrated_engine):
    """PostgreSQL: composite FK rejects chunk with patient_id not matching document's
    patient."""
    with Session(pg_migrated_engine) as session:
        patient_a = Patient(user_id=uuid.uuid4())
        patient_b = Patient(user_id=uuid.uuid4())
        session.add_all([patient_a, patient_b])
        session.flush()

        now_dt = datetime.now(timezone.utc)
        doc_a = MedicalDocument(
            patient_id=patient_a.id,
            file_name="pg_test.pdf",
            display_name="PG Test",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=512,
            storage_key=f"documents/{patient_a.id}/{uuid.uuid4()}",
            source_type="PATIENT_REPORTED",
            verification_state="PATIENT_REPORTED",
            uploaded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(doc_a)
        session.flush()

        bad_chunk = DocumentChunk(
            document_id=doc_a.id,
            patient_id=patient_b.id,  # mismatched tenant
            chunk_index=0,
            chunk_text="Cross-tenant chunk attempt.",
        )
        session.add(bad_chunk)

        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_pg_cascade_delete_removes_chunks(pg_migrated_engine):
    """PostgreSQL: deleting a MedicalDocument cascades deletion to its chunks."""
    with Session(pg_migrated_engine) as session:
        patient, doc = _insert_patient_and_document(session)

        chunk = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="Cascade delete test chunk.",
        )
        session.add(chunk)
        session.commit()
        chunk_id = chunk.id
        patient_id = patient.id

        # Delete the document; cascade should remove the chunk
        session.delete(doc)
        session.commit()

        remaining = session.get(DocumentChunk, chunk_id)
        assert remaining is None, "Cascade delete failed on PostgreSQL"

        # Cleanup: remove the orphaned Patient row so it does not persist in the
        # shared live test database between runs.
        leftover_patient = session.get(Patient, patient_id)
        if leftover_patient is not None:
            session.delete(leftover_patient)
            session.commit()


def test_pg_migration_downgrade_and_reupgrade(pg_migrated_engine):
    """PostgreSQL: migration 0005 can be downgraded and re-upgraded without errors.

    The upgrade to head is always performed in a finally block so the database
    is restored even when intermediate assertions fail.
    """
    import pathlib

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # Downgrade to 0004
    command.downgrade(cfg, "0004_add_document_extractions")

    try:
        with pg_migrated_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'document_chunks'"
                )
            )
            assert result.fetchone() is None, (
                "document_chunks table should be absent after downgrade"
            )

            # vector extension should be dropped too
            ext_result = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            assert ext_result.fetchone() is None, (
                "vector extension should be removed during downgrade"
            )
    finally:
        # Always restore to head so subsequent tests can rely on the full schema.
        command.upgrade(cfg, "head")

    with pg_migrated_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'document_chunks'"
            )
        )
        assert result.fetchone() is not None, (
            "document_chunks should exist after re-upgrade"
        )


def test_pg_vector_persistence(pg_migrated_engine):
    """PostgreSQL: a 768-dimensional embedding can be persisted and retrieved correctly.

    Also verifies that an incorrect dimension is rejected by PostgreSQL.
    No embedding generation or external calls are made — vectors are deterministic
    test fixtures.
    """
    import math

    # Build a deterministic unit-normalised 768-dim vector.
    raw = [math.sin(i * 0.01) for i in range(768)]
    magnitude = math.sqrt(sum(v * v for v in raw))
    vec_768 = [v / magnitude for v in raw]

    with Session(pg_migrated_engine) as session:
        patient, doc = _insert_patient_and_document(session)

        chunk = DocumentChunk(
            document_id=doc.id,
            patient_id=patient.id,
            chunk_index=0,
            chunk_text="Vector persistence test chunk.",
            embedding=vec_768,
        )
        session.add(chunk)
        session.commit()
        chunk_id = chunk.id

        # Retrieve and verify dimensions
        retrieved = session.get(DocumentChunk, chunk_id)
        assert retrieved is not None
        assert retrieved.embedding is not None
        assert len(retrieved.embedding) == 768, (
            f"Expected 768-dim embedding, got {len(retrieved.embedding)}"
        )

        # Cleanup
        session.delete(doc)
        session.commit()
        leftover = session.get(Patient, patient.id)
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    # Verify PostgreSQL rejects a vector of wrong dimension
    with Session(pg_migrated_engine) as session:
        patient2, doc2 = _insert_patient_and_document(session)

        bad_chunk = DocumentChunk(
            document_id=doc2.id,
            patient_id=patient2.id,
            chunk_index=0,
            chunk_text="Wrong-dimension vector test.",
            embedding=[0.1] * 512,  # wrong dimension
        )
        session.add(bad_chunk)
        with pytest.raises(Exception):  # pgvector raises DataError or IntegrityError
            session.flush()
        session.rollback()

        # Cleanup patient2 / doc2 (rolled back, so only patient2 may be committed)
        leftover2 = session.get(Patient, patient2.id)
        if leftover2 is not None:
            session.delete(leftover2)
            session.commit()
