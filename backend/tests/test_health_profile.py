import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Patient
from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_get_empty_health_profile(async_client: AsyncClient):
    """Verify GET /api/v1/health-profile returns an empty profile for new users."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    response = await async_client.get(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] is None
    assert data["patient_id"] is not None
    assert data["date_of_birth"] is None
    assert data["biological_sex"] is None
    assert data["height_cm"] is None
    assert data["blood_group"] is None
    assert data["notes"] is None
    assert data["created_at"] is None
    assert data["updated_at"] is None


async def test_create_health_profile(async_client: AsyncClient):
    """Verify PUT /api/v1/health-profile creates a new profile with provided fields."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "date_of_birth": "1992-04-12",
        "biological_sex": "female",
        "height_cm": 165.50,
        "blood_group": "B+",
        "notes": "No known health conditions.",
    }

    response = await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["date_of_birth"] == "1992-04-12"
    assert data["biological_sex"] == "female"
    assert float(data["height_cm"]) == 165.50
    assert data["blood_group"] == "B+"
    assert data["notes"] == "No known health conditions."
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


async def test_update_health_profile_persists(async_client: AsyncClient):
    """Verify updating health profile fields persists.

    Re-fetch returns updated values.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # Initial creation
    init_payload = {
        "date_of_birth": "1988-11-20",
        "biological_sex": "male",
        "height_cm": 180.00,
        "blood_group": "O+",
        "notes": "Initial notes",
    }
    create_res = await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
        json=init_payload,
    )
    assert create_res.status_code == 200
    initial_id = create_res.json()["id"]

    # Update subset of fields
    update_payload = {
        "height_cm": 181.50,
        "notes": "Updated after checkup",
    }
    update_res = await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
        json=update_payload,
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["id"] == initial_id
    assert float(updated_data["height_cm"]) == 181.50
    assert updated_data["notes"] == "Updated after checkup"
    assert updated_data["biological_sex"] == "male"
    assert updated_data["blood_group"] == "O+"

    # Re-fetch via GET to confirm database persistence
    get_res = await async_client.get(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    fetched_data = get_res.json()
    assert fetched_data["id"] == initial_id
    assert float(fetched_data["height_cm"]) == 181.50
    assert fetched_data["notes"] == "Updated after checkup"
    assert fetched_data["biological_sex"] == "male"
    assert fetched_data["date_of_birth"] == "1988-11-20"


async def test_cross_user_isolation(async_client: AsyncClient):
    """Verify strict user isolation: User B cannot access User A's profile."""
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a_id)
    token_b = create_test_token(user_id=user_b_id)

    # User A creates their profile
    await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "biological_sex": "female",
            "blood_group": "AB-",
            "notes": "User A confidential data",
        },
    )

    # User B fetches profile -> must be empty, not User A's profile
    res_b = await async_client.get(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["id"] is None
    assert data_b["notes"] is None
    assert data_b["blood_group"] is None

    # User B updates their profile
    await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "biological_sex": "male",
            "blood_group": "O+",
            "notes": "User B data",
        },
    )

    # User A fetches profile -> must remain User A's data untouched
    res_a = await async_client.get(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["notes"] == "User A confidential data"
    assert data_a["blood_group"] == "AB-"
    assert data_a["biological_sex"] == "female"
    assert data_a["patient_id"] != data_b["patient_id"]


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests to health-profile return 401."""
    get_res = await async_client.get("/api/v1/health-profile")
    assert get_res.status_code == 401

    put_res = await async_client.put(
        "/api/v1/health-profile",
        json={"notes": "No auth"},
    )
    assert put_res.status_code == 401


async def test_patient_auto_created_on_health_profile_access(
    async_client: AsyncClient, db
):
    """Verify patient record is auto-created in database upon health-profile access."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    response = await async_client.get(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    patient_id = response.json()["patient_id"]

    # Verify in DB that patient was auto-created for this user_id
    stmt = select(Patient).where(Patient.user_id == uuid.UUID(user_id))
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()
    assert patient is not None
    assert str(patient.id) == patient_id
