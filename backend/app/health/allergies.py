import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Allergy


async def get_allergies(db: AsyncSession, patient_id: uuid.UUID) -> list[Allergy]:
    """Retrieve all allergies belonging to a patient, ordered chronologically."""
    stmt = (
        select(Allergy)
        .where(Allergy.patient_id == patient_id)
        .order_by(Allergy.recorded_at.desc(), Allergy.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_allergy_by_id(
    db: AsyncSession, allergy_id: uuid.UUID
) -> Optional[Allergy]:
    """Retrieve a specific allergy by its ID."""
    stmt = select(Allergy).where(Allergy.id == allergy_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_allergy(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> Allergy:
    """Create a new allergy for a patient, enforcing server-side provenance."""
    allergy_data = {k: v for k, v in data.items() if v is not None}
    allergy_data["source_type"] = "PATIENT_REPORTED"
    allergy = Allergy(patient_id=patient_id, **allergy_data)
    db.add(allergy)
    await db.commit()
    await db.refresh(allergy)
    return allergy


async def update_allergy(
    db: AsyncSession, allergy: Allergy, data: dict[str, Any]
) -> Allergy:
    """Update an existing allergy, ignoring any client-supplied source_type."""
    for key, value in data.items():
        if key != "source_type":
            setattr(allergy, key, value)
    await db.commit()
    await db.refresh(allergy)
    return allergy


async def delete_allergy(db: AsyncSession, allergy: Allergy) -> None:
    """Delete an allergy."""
    await db.delete(allergy)
    await db.commit()
