from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.patient import get_or_create_patient
from app.health.profile import get_health_profile, upsert_health_profile
from app.schemas.health_profile import HealthProfileResponse, HealthProfileUpdate

router = APIRouter(prefix="/health-profile", tags=["health-profile"])


@router.get("", response_model=HealthProfileResponse)
async def get_my_health_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthProfileResponse:
    """Fetch the authenticated user's health profile.

    If no profile exists yet, returns an empty profile with default/null fields.
    """
    patient = await get_or_create_patient(db, current_user.id)
    profile = await get_health_profile(db, patient.id)
    await db.commit()
    if profile is None:
        return HealthProfileResponse(patient_id=patient.id)
    return HealthProfileResponse.model_validate(profile)


@router.put("", response_model=HealthProfileResponse)
async def update_my_health_profile(
    profile_in: HealthProfileUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthProfileResponse:
    """Create or update (upsert) the authenticated user's health profile."""
    patient = await get_or_create_patient(db, current_user.id)
    data = profile_in.model_dump(exclude_unset=True)
    profile = await upsert_health_profile(db, patient.id, data)
    return HealthProfileResponse.model_validate(profile)
