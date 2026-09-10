import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HealthProfile


async def get_health_profile(
    db: AsyncSession, patient_id: uuid.UUID
) -> Optional[HealthProfile]:
    """Retrieve the health profile for a given patient_id, or None if not found."""
    stmt = select(HealthProfile).where(HealthProfile.patient_id == patient_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_health_profile(
    db: AsyncSession, patient_id: uuid.UUID, data: dict[str, Any]
) -> HealthProfile:
    """Create or update (upsert) the health profile for a given patient_id."""
    profile = await get_health_profile(db, patient_id)
    if profile is None:
        profile = HealthProfile(patient_id=patient_id, **data)
        db.add(profile)
    else:
        for key, value in data.items():
            setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile)
    return profile
