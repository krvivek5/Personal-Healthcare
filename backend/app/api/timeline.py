from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.health.patient import get_or_create_patient
from app.health.timeline import get_timeline
from app.schemas.timeline import HealthEvent

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("", response_model=list[HealthEvent])
async def get_my_timeline(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HealthEvent]:
    """
    Retrieve the chronological health timeline for the authenticated patient.

    Synthesizes meaningful health events across conditions, symptoms,
    medications, documents, and patient goals.
    Strictly isolated to the authenticated user's patient entity.
    """
    patient = await get_or_create_patient(db, current_user.id)
    events = await get_timeline(db, patient.id)
    await db.commit()
    return events
