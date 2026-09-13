import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.allergies import (
    create_allergy,
    delete_allergy,
    get_allergies,
    get_allergy_by_id,
    update_allergy,
)
from app.health.patient import get_or_create_patient
from app.schemas.allergy import (
    AllergyCreate,
    AllergyResponse,
    AllergyUpdate,
)

router = APIRouter(prefix="/allergies", tags=["allergies"])


@router.get("", response_model=list[AllergyResponse])
async def list_my_allergies(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AllergyResponse]:
    """List all allergies belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    allergies = await get_allergies(db, patient.id)
    await db.commit()
    return [AllergyResponse.model_validate(a) for a in allergies]


@router.post(
    "",
    response_model=AllergyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_allergy(
    allergy_in: AllergyCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AllergyResponse:
    """Create a new allergy for the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    data = allergy_in.model_dump(exclude_unset=True)
    allergy = await create_allergy(db, patient.id, data)
    return AllergyResponse.model_validate(allergy)


@router.get("/{allergy_id}", response_model=AllergyResponse)
async def get_allergy(
    allergy_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AllergyResponse:
    """Get a specific allergy by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    allergy = await get_allergy_by_id(db, allergy_id)
    if allergy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allergy not found",
        )
    if allergy.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return AllergyResponse.model_validate(allergy)


@router.patch("/{allergy_id}", response_model=AllergyResponse)
async def patch_allergy(
    allergy_id: uuid.UUID,
    allergy_in: AllergyUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AllergyResponse:
    """Update a specific allergy by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    allergy = await get_allergy_by_id(db, allergy_id)
    if allergy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allergy not found",
        )
    if allergy.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = allergy_in.model_dump(exclude_unset=True)
    updated = await update_allergy(db, allergy, data, patient.id)
    return AllergyResponse.model_validate(updated)


@router.delete(
    "/{allergy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_allergy(
    allergy_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an allergy, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    allergy = await get_allergy_by_id(db, allergy_id)
    if allergy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allergy not found",
        )
    if allergy.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await delete_allergy(db, allergy)
    return None
