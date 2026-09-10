import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


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
