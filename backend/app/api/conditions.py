import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.conditions import (
    create_condition,
    delete_condition,
    get_condition_by_id,
    get_conditions,
    update_condition,
)
from app.health.patient import get_or_create_patient
from app.schemas.condition import (
    ConditionCreate,
    ConditionResponse,
    ConditionUpdate,
)

router = APIRouter(prefix="/conditions", tags=["conditions"])


@router.get("", response_model=list[ConditionResponse])
async def list_my_conditions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConditionResponse]:
    """List all conditions belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    conditions = await get_conditions(db, patient.id)
    await db.commit()
    return [ConditionResponse.model_validate(c) for c in conditions]


@router.post(
    "",
    response_model=ConditionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_condition(
    condition_in: ConditionCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConditionResponse:
    """Create a new condition for the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    data = condition_in.model_dump(exclude_unset=True)
    condition = await create_condition(db, patient.id, data)
    return ConditionResponse.model_validate(condition)


@router.get("/{condition_id}", response_model=ConditionResponse)
async def get_condition(
    condition_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConditionResponse:
    """Get a specific condition by ID, enforcing user/patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    condition = await get_condition_by_id(db, condition_id)
    if condition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition not found",
        )
    if condition.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return ConditionResponse.model_validate(condition)


@router.patch("/{condition_id}", response_model=ConditionResponse)
async def patch_condition(
    condition_id: uuid.UUID,
    condition_in: ConditionUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConditionResponse:
    """Update a specific condition by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    condition = await get_condition_by_id(db, condition_id)
    if condition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition not found",
        )
    if condition.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = condition_in.model_dump(exclude_unset=True)
    updated = await update_condition(db, condition, data, patient.id)
    return ConditionResponse.model_validate(updated)


@router.delete(
    "/{condition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_condition(
    condition_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a condition, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    condition = await get_condition_by_id(db, condition_id)
    if condition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition not found",
        )
    if condition.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await delete_condition(db, condition)
    return None
