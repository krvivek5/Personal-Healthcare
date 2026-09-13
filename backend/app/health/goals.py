import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PatientGoal
from app.health.provenance import validate_and_resolve_provenance


async def get_goals(db: AsyncSession, patient_id: uuid.UUID) -> list[PatientGoal]:
    """Retrieve all goals belonging to a patient, ordered by recorded_at descending."""
    stmt = (
        select(PatientGoal)
        .where(PatientGoal.patient_id == patient_id)
        .order_by(PatientGoal.recorded_at.desc(), PatientGoal.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_goal_by_id(db: AsyncSession, goal_id: uuid.UUID) -> Optional[PatientGoal]:
    """Retrieve a specific goal by its ID."""
    stmt = select(PatientGoal).where(PatientGoal.id == goal_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_goal(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> PatientGoal:
    """Create a new goal for a patient with validated provenance."""
    data = await validate_and_resolve_provenance(db, patient_id, data)
    goal = PatientGoal(patient_id=patient_id, **data)
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return goal


async def update_goal(
    db: AsyncSession, goal: PatientGoal, data: dict[str, Any], patient_id: uuid.UUID
) -> PatientGoal:
    """Update an existing goal with provenance validation."""
    data = await validate_and_resolve_provenance(
        db,
        patient_id,
        data,
        existing_source_type=goal.source_type,
        existing_source_id=goal.source_id,
    )
    for key, value in data.items():
        setattr(goal, key, value)
    await db.commit()
    await db.refresh(goal)
    return goal


async def delete_goal(db: AsyncSession, goal: PatientGoal) -> None:
    """Delete a goal."""
    await db.delete(goal)
    await db.commit()
