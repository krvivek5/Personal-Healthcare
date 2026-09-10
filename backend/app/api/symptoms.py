import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.patient import get_or_create_patient
from app.health.symptoms import (
    create_symptom,
    delete_symptom,
    get_symptom_by_id,
    get_symptoms,
    update_symptom,
)
from app.schemas.symptom import (
    SymptomCreate,
    SymptomResponse,
    SymptomUpdate,
)

router = APIRouter(prefix="/symptoms", tags=["symptoms"])


@router.get("", response_model=list[SymptomResponse])
async def list_my_symptoms(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SymptomResponse]:
    """List all symptoms belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    symptoms = await get_symptoms(db, patient.id)
    await db.commit()
    return [SymptomResponse.model_validate(s) for s in symptoms]


@router.post(
    "",
    response_model=SymptomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_symptom(
    symptom_in: SymptomCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SymptomResponse:
    """Create a new symptom for the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    data = symptom_in.model_dump(exclude_unset=True)
    symptom = await create_symptom(db, patient.id, data)
    return SymptomResponse.model_validate(symptom)


@router.get("/{symptom_id}", response_model=SymptomResponse)
async def get_symptom(
    symptom_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SymptomResponse:
    """Get a specific symptom by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    symptom = await get_symptom_by_id(db, symptom_id)
    if symptom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Symptom not found",
        )
    if symptom.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return SymptomResponse.model_validate(symptom)


@router.patch("/{symptom_id}", response_model=SymptomResponse)
async def patch_symptom(
    symptom_id: uuid.UUID,
    symptom_in: SymptomUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SymptomResponse:
    """Update a specific symptom by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    symptom = await get_symptom_by_id(db, symptom_id)
    if symptom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Symptom not found",
        )
    if symptom.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = symptom_in.model_dump(exclude_unset=True)
    updated = await update_symptom(db, symptom, data)
    return SymptomResponse.model_validate(updated)


@router.delete(
    "/{symptom_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_symptom(
    symptom_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a symptom, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    symptom = await get_symptom_by_id(db, symptom_id)
    if symptom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Symptom not found",
        )
    if symptom.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await delete_symptom(db, symptom)
    return None
