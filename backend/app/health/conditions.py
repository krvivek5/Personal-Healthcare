import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Condition
from app.health.provenance import validate_and_resolve_provenance


async def get_conditions(db: AsyncSession, patient_id: uuid.UUID) -> list[Condition]:
    """Retrieve all conditions belonging to a patient, ordered chronologically."""
    stmt = (
        select(Condition)
        .where(Condition.patient_id == patient_id)
        .order_by(Condition.recorded_at.desc(), Condition.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_condition_by_id(
    db: AsyncSession, condition_id: uuid.UUID
) -> Optional[Condition]:
    """Retrieve a specific condition by its ID."""
    stmt = select(Condition).where(Condition.id == condition_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_condition(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> Condition:
    """Create a new condition for a patient with validated provenance."""
    data = await validate_and_resolve_provenance(db, patient_id, data)
    condition = Condition(patient_id=patient_id, **data)
    db.add(condition)
    await db.commit()
    await db.refresh(condition)
    return condition


async def update_condition(
    db: AsyncSession, condition: Condition, data: dict[str, Any], patient_id: uuid.UUID
) -> Condition:
    """Update an existing condition with provenance validation."""
    data = await validate_and_resolve_provenance(
        db,
        patient_id,
        data,
        existing_source_type=condition.source_type,
        existing_source_id=condition.source_id,
    )
    for key, value in data.items():
        setattr(condition, key, value)
    await db.commit()
    await db.refresh(condition)
    return condition


async def delete_condition(db: AsyncSession, condition: Condition) -> None:
    """Delete a condition."""
    await db.delete(condition)
    await db.commit()
