import uuid
from typing import Union

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient


async def get_or_create_patient(
    db: AsyncSession, user_id: Union[uuid.UUID, str]
) -> Patient:
    """Resolve or create the user's patient identity.

    This acts as the identity bridge between the authenticated user (user_id)
    and their health records (patient_id). Returns the existing patient for the user,
    or creates one atomically if none exists.
    """
    if isinstance(user_id, str):
        user_id = uuid.UUID(user_id)

    # Atomically get or insert using PostgreSQL ON CONFLICT DO NOTHING
    stmt = (
        insert(Patient)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=["user_id"])
        .returning(Patient)
    )
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()

    if patient is None:
        # The ON CONFLICT DO NOTHING triggered, meaning the patient already exists.
        select_stmt = select(Patient).where(Patient.user_id == user_id)
        result = await db.execute(select_stmt)
        patient = result.scalar_one()

    return patient
