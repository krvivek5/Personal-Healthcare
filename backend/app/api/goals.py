import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.goals import (
    create_goal,
    delete_goal,
    get_goal_by_id,
    get_goals,
    update_goal,
)
from app.health.patient import get_or_create_patient
from app.schemas.goal import GoalCreate, GoalResponse, GoalUpdate

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalResponse])
async def list_my_goals(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GoalResponse]:
    """List all goals belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    goals = await get_goals(db, patient.id)
    await db.commit()
    return [GoalResponse.model_validate(g) for g in goals]


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def add_goal(
    goal_in: GoalCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalResponse:
    """Create a new goal for the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    data = goal_in.model_dump(exclude_unset=True)
    goal = await create_goal(db, patient.id, data)
    return GoalResponse.model_validate(goal)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalResponse:
    """Get a specific goal by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    goal = await get_goal_by_id(db, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found",
        )
    if goal.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return GoalResponse.model_validate(goal)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def patch_goal(
    goal_id: uuid.UUID,
    goal_in: GoalUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalResponse:
    """Update a specific goal by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    goal = await get_goal_by_id(db, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found",
        )
    if goal.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = goal_in.model_dump(exclude_unset=True)
    updated = await update_goal(db, goal, data)
    return GoalResponse.model_validate(updated)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_goal(
    goal_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a goal, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    goal = await get_goal_by_id(db, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found",
        )
    if goal.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await delete_goal(db, goal)
    return None
