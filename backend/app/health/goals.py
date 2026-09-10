import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PatientGoal


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
    """Create a new goal for a patient."""
    goal_data = {k: v for k, v in data.items() if v is not None}
    goal = PatientGoal(patient_id=patient_id, **goal_data)
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return goal


async def update_goal(
    db: AsyncSession, goal: PatientGoal, data: dict[str, Any]
) -> PatientGoal:
    """Update an existing goal with the supplied fields."""
    for key, value in data.items():
        setattr(goal, key, value)
    await db.commit()
    await db.refresh(goal)
    return goal


async def delete_goal(db: AsyncSession, goal: PatientGoal) -> None:
    """Delete a goal."""
    await db.delete(goal)
    await db.commit()
