import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Symptom
from app.health.provenance import validate_and_resolve_provenance


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
    """Create a new symptom for a patient with validated provenance."""
    data = await validate_and_resolve_provenance(db, patient_id, data)
    symptom = Symptom(patient_id=patient_id, **data)
    db.add(symptom)
    await db.commit()
    await db.refresh(symptom)
    return symptom


async def update_symptom(
    db: AsyncSession, symptom: Symptom, data: dict[str, Any], patient_id: uuid.UUID
) -> Symptom:
    """Update an existing symptom with provenance validation."""
    data = await validate_and_resolve_provenance(
        db,
        patient_id,
        data,
        existing_source_type=symptom.source_type,
        existing_source_id=symptom.source_id,
    )
    for key, value in data.items():
        setattr(symptom, key, value)
    await db.commit()
    await db.refresh(symptom)
    return symptom


async def delete_symptom(db: AsyncSession, symptom: Symptom) -> None:
    """Delete a symptom."""
    await db.delete(symptom)
    await db.commit()
