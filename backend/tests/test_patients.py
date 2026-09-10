import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient
from app.health.patient import get_or_create_patient

pytestmark = pytest.mark.asyncio


async def test_patient_auto_creation_on_first_access(db: AsyncSession):
    """Test that a patient is created if one does not exist for the user_id."""
    user_id = uuid.uuid4()

    # Ensure patient doesn't exist initially
    stmt = select(Patient).where(Patient.user_id == user_id)
    result = await db.execute(stmt)
    assert result.scalar_one_or_none() is None

    # Call get_or_create
    patient = await get_or_create_patient(db, user_id)

    assert patient is not None
    assert patient.user_id == user_id
    assert patient.id is not None

    # Verify it exists in DB
    result = await db.execute(stmt)
    db_patient = result.scalar_one_or_none()
    assert db_patient is not None
    assert db_patient.id == patient.id


async def test_same_user_resolves_to_same_patient(db: AsyncSession):
    """Test that subsequent calls return the exact same patient."""
    user_id = uuid.uuid4()

    # First call creates the patient
    patient1 = await get_or_create_patient(db, user_id)
    assert patient1 is not None

    # Second call fetches the existing patient
    patient2 = await get_or_create_patient(db, user_id)
    assert patient2 is not None

    assert patient1.id == patient2.id
    assert patient1.user_id == patient2.user_id


async def test_patient_cross_user_isolation(db: AsyncSession):
    """Test that different users resolve to different patients."""
    user_id_a = uuid.uuid4()
    user_id_b = uuid.uuid4()

    patient_a = await get_or_create_patient(db, user_id_a)
    patient_b = await get_or_create_patient(db, user_id_b)

    assert patient_a is not None
    assert patient_b is not None
    assert patient_a.id != patient_b.id
    assert patient_a.user_id == user_id_a
    assert patient_b.user_id == user_id_b
