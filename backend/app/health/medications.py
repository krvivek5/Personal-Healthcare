import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Medication


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
    """Create a new medication for a patient, enforcing server-side provenance."""
    medication_data = {k: v for k, v in data.items() if v is not None}
    medication_data["source_type"] = "PATIENT_REPORTED"
    medication = Medication(patient_id=patient_id, **medication_data)
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return medication


async def update_medication(
    db: AsyncSession, medication: Medication, data: dict[str, Any]
) -> Medication:
    """Update an existing medication, ignoring any client-supplied source_type."""
    for key, value in data.items():
        if key != "source_type":
            setattr(medication, key, value)
    await db.commit()
    await db.refresh(medication)
    return medication


async def delete_medication(db: AsyncSession, medication: Medication) -> None:
    """Delete a medication."""
    await db.delete(medication)
    await db.commit()
