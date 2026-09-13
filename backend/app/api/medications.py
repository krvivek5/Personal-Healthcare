import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.medications import (
    create_medication,
    delete_medication,
    get_medication_by_id,
    get_medications,
    update_medication,
)
from app.health.patient import get_or_create_patient
from app.schemas.medication import (
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
)

router = APIRouter(prefix="/medications", tags=["medications"])


@router.get("", response_model=list[MedicationResponse])
async def list_my_medications(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MedicationResponse]:
    """List all medications belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    medications = await get_medications(db, patient.id)
    await db.commit()
    return [MedicationResponse.model_validate(m) for m in medications]


@router.post(
    "",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_medication(
    medication_in: MedicationCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MedicationResponse:
    """Create a new medication for the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    data = medication_in.model_dump(exclude_unset=True)
    medication = await create_medication(db, patient.id, data)
    return MedicationResponse.model_validate(medication)


@router.get("/{medication_id}", response_model=MedicationResponse)
async def get_medication(
    medication_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MedicationResponse:
    """Get a specific medication by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    medication = await get_medication_by_id(db, medication_id)
    if medication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medication not found",
        )
    if medication.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return MedicationResponse.model_validate(medication)


@router.patch("/{medication_id}", response_model=MedicationResponse)
async def patch_medication(
    medication_id: uuid.UUID,
    medication_in: MedicationUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MedicationResponse:
    """Update a specific medication by ID, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    medication = await get_medication_by_id(db, medication_id)
    if medication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medication not found",
        )
    if medication.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = medication_in.model_dump(exclude_unset=True)
    updated = await update_medication(db, medication, data, patient.id)
    return MedicationResponse.model_validate(updated)


@router.delete(
    "/{medication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_medication(
    medication_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a medication, enforcing patient isolation."""
    patient = await get_or_create_patient(db, current_user.id)
    medication = await get_medication_by_id(db, medication_id)
    if medication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medication not found",
        )
    if medication.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await delete_medication(db, medication)
    return None
