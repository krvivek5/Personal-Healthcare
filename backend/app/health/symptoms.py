import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Symptom


async def get_symptoms(db: AsyncSession, patient_id: uuid.UUID) -> list[Symptom]:
    """Retrieve all symptoms belonging to a patient, ordered chronologically."""
    stmt = (
        select(Symptom)
        .where(Symptom.patient_id == patient_id)
        .order_by(Symptom.recorded_at.desc(), Symptom.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_symptom_by_id(
    db: AsyncSession, symptom_id: uuid.UUID
) -> Optional[Symptom]:
    """Retrieve a specific symptom by its ID."""
    stmt = select(Symptom).where(Symptom.id == symptom_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_symptom(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> Symptom:
    """Create a new symptom for a patient, enforcing server-side provenance."""
    symptom_data = {k: v for k, v in data.items() if v is not None}
    symptom_data["source_type"] = "PATIENT_REPORTED"
    symptom = Symptom(patient_id=patient_id, **symptom_data)
    db.add(symptom)
    await db.commit()
    await db.refresh(symptom)
    return symptom


async def update_symptom(
    db: AsyncSession, symptom: Symptom, data: dict[str, Any]
) -> Symptom:
    """Update an existing symptom, ignoring any client-supplied source_type."""
    for key, value in data.items():
        if key != "source_type":
            setattr(symptom, key, value)
    await db.commit()
    await db.refresh(symptom)
    return symptom


async def delete_symptom(db: AsyncSession, symptom: Symptom) -> None:
    """Delete a symptom."""
    await db.delete(symptom)
    await db.commit()
