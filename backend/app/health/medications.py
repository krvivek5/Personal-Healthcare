import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Medication
from app.health.provenance import validate_and_resolve_provenance


async def get_medications(db: AsyncSession, patient_id: uuid.UUID) -> list[Medication]:
    """Retrieve all medications belonging to a patient, ordered chronologically."""
    stmt = (
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.recorded_at.desc(), Medication.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_medication_by_id(
    db: AsyncSession, medication_id: uuid.UUID
) -> Optional[Medication]:
    """Retrieve a specific medication by its ID."""
    stmt = select(Medication).where(Medication.id == medication_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_medication(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> Medication:
    """Create a new medication for a patient with validated provenance."""
    data = await validate_and_resolve_provenance(db, patient_id, data)
    medication = Medication(patient_id=patient_id, **data)
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return medication


async def update_medication(
    db: AsyncSession,
    medication: Medication,
    data: dict[str, Any],
    patient_id: uuid.UUID,
) -> Medication:
    """Update an existing medication with provenance validation."""
    data = await validate_and_resolve_provenance(
        db,
        patient_id,
        data,
        existing_source_type=medication.source_type,
        existing_source_id=medication.source_id,
    )
    for key, value in data.items():
        setattr(medication, key, value)
    await db.commit()
    await db.refresh(medication)
    return medication


async def delete_medication(db: AsyncSession, medication: Medication) -> None:
    """Delete a medication."""
    await db.delete(medication)
    await db.commit()
