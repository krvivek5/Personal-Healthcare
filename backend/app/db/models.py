import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base


# ---------------------------------------------------------------------------
# SQLite dialect fallback for pgvector Vector type.
# This allows SQLite-based offline test suites to load models without errors.
# The Vector(768) column is stored as TEXT in SQLite.
# ---------------------------------------------------------------------------
@compiles(Vector, "sqlite")
def _visit_vector_sqlite(type_: Vector, compiler: object, **kw: object) -> str:  # type: ignore[override]
    return "TEXT"


class Patient(Base):
    """Patient entity representing a person whose health data is stored."""

    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    health_profile: Mapped[Optional["HealthProfile"]] = relationship(
        "HealthProfile",
        back_populates="patient",
        uselist=False,
        cascade="all, delete-orphan",
    )
    conditions: Mapped[list["Condition"]] = relationship(
        "Condition",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    symptoms: Mapped[list["Symptom"]] = relationship(
        "Symptom",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    medications: Mapped[list["Medication"]] = relationship(
        "Medication",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    allergies: Mapped[list["Allergy"]] = relationship(
        "Allergy",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    goals: Mapped[list["PatientGoal"]] = relationship(
        "PatientGoal",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["MedicalDocument"]] = relationship(
        "MedicalDocument",
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class HealthProfile(Base):
    """Demographic and core health profile for a patient."""

    __tablename__ = "health_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    biological_sex: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    height_cm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    blood_group: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="health_profile",
    )


class Condition(Base):
    """Diagnosed or patient-reported health condition."""

    __tablename__ = "conditions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,  # active | resolved
    )
    is_chronic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    started_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    ended_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="conditions",
    )


class Symptom(Base):
    """Reported symptom experienced by a patient."""

    __tablename__ = "symptoms"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    severity: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,  # mild | moderate | severe
    )
    started_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    ended_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="symptoms",
    )


class Medication(Base):
    """Medication taken by a patient."""

    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    dosage: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    frequency: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,  # active | stopped
    )
    as_needed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    started_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    ended_at: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="medications",
    )


class Allergy(Base):
    """Allergy recorded for a patient."""

    __tablename__ = "allergies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    allergen: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    reaction: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    severity: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,  # mild | moderate | severe | life_threatening
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="allergies",
    )


class PatientGoal(Base):
    """Personal health goal defined by a patient."""

    __tablename__ = "patient_goals"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,  # active | achieved | abandoned
    )
    target_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="goals",
    )


class MedicalDocument(Base):
    """Medical document uploaded by a patient.

    The original file is stored in S3 under storage_key.
    storage_key is internal and must never be exposed to API clients.

    Provenance invariants (enforced via DB CHECK constraints in migration 0003):
      - source_type is always 'PATIENT_REPORTED'
      - verification_state is always 'PATIENT_REPORTED'
      - No source_id column (no document-to-document chains)
    """

    __tablename__ = "medical_documents"
    __table_args__ = (
        UniqueConstraint("id", "patient_id", name="uq_medical_documents_id_patient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    # Internal S3 object key — NEVER exposed to API clients.
    storage_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    document_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    verification_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PATIENT_REPORTED",
        server_default="PATIENT_REPORTED",
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="documents",
    )
    document_extraction: Mapped[Optional["DocumentExtraction"]] = relationship(
        "DocumentExtraction",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentExtraction(Base):
    """Derived text content extracted from a canonical MedicalDocument."""

    __tablename__ = "document_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "patient_id"],
            ["medical_documents.id", "medical_documents.patient_id"],
            name="fk_document_extractions_document_patient",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "extraction_status IN ('COMPLETED', 'FAILED', 'UNSUPPORTED')",
            name="ck_document_extractions_extraction_status",
        ),
        CheckConstraint(
            "(extraction_status = 'COMPLETED' "
            "AND extracted_text IS NOT NULL "
            "AND length(trim(extracted_text)) > 0) "
            "OR (extraction_status IN ('FAILED', 'UNSUPPORTED') "
            "AND (extracted_text IS NULL OR length(trim(extracted_text)) = 0))",
            name="ck_document_extractions_status_content",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extracted_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    extraction_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    extraction_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    extraction_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationship
    document: Mapped["MedicalDocument"] = relationship(
        "MedicalDocument",
        back_populates="document_extraction",
    )

    @validates("patient_id")
    def validate_patient_id(self, key: str, value: uuid.UUID) -> uuid.UUID:
        if (
            hasattr(self, "document")
            and self.document is not None
            and self.document.patient_id != value
        ):
            raise ValueError(
                f"Tenant integrity violation: extraction patient_id ({value}) "
                f"does not match document patient_id ({self.document.patient_id})"
            )
        return value

    @validates("document")
    def validate_document(
        self, key: str, value: Optional["MedicalDocument"]
    ) -> Optional["MedicalDocument"]:
        if (
            value is not None
            and hasattr(self, "patient_id")
            and self.patient_id is not None
            and value.patient_id != self.patient_id
        ):
            raise ValueError(
                f"Tenant integrity violation: extraction patient_id "
                f"({self.patient_id}) does not match document patient_id "
                f"({value.patient_id})"
            )
        return value

    @validates("extracted_text", "extraction_status")
    def validate_content_and_status(self, key: str, value: Any) -> Any:
        status = (
            value
            if key == "extraction_status"
            else getattr(self, "extraction_status", None)
        )
        text = (
            value if key == "extracted_text" else getattr(self, "extracted_text", None)
        )

        if status == "COMPLETED":
            if key == "extracted_text" and (value is None or not str(value).strip()):
                raise ValueError(
                    "COMPLETED extraction status requires non-empty extracted_text"
                )
            elif (
                key == "extraction_status"
                and text is not None
                and not str(text).strip()
            ):
                raise ValueError(
                    "COMPLETED extraction status requires non-empty extracted_text"
                )
        elif status in ("FAILED", "UNSUPPORTED"):
            if key == "extracted_text" and value is not None and str(value).strip():
                raise ValueError(
                    f"{status} extraction status permits only null "
                    "or empty extracted_text"
                )
            elif key == "extraction_status" and text is not None and str(text).strip():
                raise ValueError(
                    f"{status} extraction status permits only null "
                    "or empty extracted_text"
                )
        return value


class DocumentChunk(Base):
    """Derived text chunk from a canonical MedicalDocument, with optional vector
    embedding.

    Each chunk belongs to exactly one (document_id, patient_id) pair, enforced by
    the composite FK to medical_documents. The embedding column holds a 768-dimensional
    pgvector embedding on PostgreSQL; on SQLite it is stored as TEXT for testing.

    Lifecycle invariants (see S1 plan §6):
      - Chunks are derived data; medical_documents remains the canonical authority.
      - chunk_index uniqueness within a document prevents duplicate passages.
      - Non-empty chunk_text is enforced at the DB level.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "patient_id"],
            ["medical_documents.id", "medical_documents.patient_id"],
            name="fk_document_chunks_document_patient",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_chunk_index",
        ),
        CheckConstraint(
            "length(trim(chunk_text)) > 0",
            name="ck_document_chunks_non_empty_text",
        ),
        Index("ix_document_chunks_patient_document", "patient_id", "document_id"),
        # HNSW cosine vector index — PostgreSQL only; ignored silently on SQLite
        # because postgresql_using/postgresql_ops kwargs are no-ops for other dialects.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    page_number: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    chunk_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(768),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped["MedicalDocument"] = relationship(
        "MedicalDocument",
        back_populates="chunks",
    )
