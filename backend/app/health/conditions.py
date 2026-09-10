import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Condition


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
    """Create a new condition for a patient."""
    condition_data = {k: v for k, v in data.items() if v is not None}
    condition_data["source_type"] = "PATIENT_REPORTED"
    condition = Condition(patient_id=patient_id, **condition_data)
    db.add(condition)
    await db.commit()
    await db.refresh(condition)
    return condition


async def update_condition(
    db: AsyncSession, condition: Condition, data: dict[str, Any]
) -> Condition:
    """Update an existing condition."""
    for key, value in data.items():
        if key != "source_type":
            setattr(condition, key, value)
    await db.commit()
    await db.refresh(condition)
    return condition


async def delete_condition(db: AsyncSession, condition: Condition) -> None:
    """Delete a condition."""
    await db.delete(condition)
    await db.commit()
