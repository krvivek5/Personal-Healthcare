import uuid

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_create_medication_and_defaults(async_client: AsyncClient):
    """Verify medication creation and default source_type=PATIENT_REPORTED."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Ibuprofen",
        "dosage": "400mg",
        "frequency": "twice daily",
        "status": "active",
        "as_needed": False,
        "notes": "Take with food",
    }
    response = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["name"] == "Ibuprofen"
    assert data["dosage"] == "400mg"
    assert data["frequency"] == "twice daily"
    assert data["status"] == "active"
    assert data["as_needed"] is False
    assert data["notes"] == "Take with food"
    assert data["source_type"] == "PATIENT_REPORTED"
    assert data["recorded_at"] is not None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


async def test_crud_lifecycle(async_client: AsyncClient):
    """Verify full CRUD lifecycle: create, read, update, delete."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Create
    create_res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Metformin",
            "dosage": "500mg",
            "frequency": "once daily",
            "status": "active",
        },
    )
    assert create_res.status_code == 201
    med_id = create_res.json()["id"]

    # 2. Read (get by ID)
    get_res = await async_client.get(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Metformin"
    assert get_res.json()["dosage"] == "500mg"

    # 3. Update (patch) — change status and add notes
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "stopped",
            "notes": "Discontinued due to side effects",
        },
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["status"] == "stopped"
    assert updated_data["notes"] == "Discontinued due to side effects"
    assert updated_data["name"] == "Metformin"  # preserved
    assert updated_data["dosage"] == "500mg"  # preserved

    # 4. Delete
    delete_res = await async_client.delete(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_res.status_code == 204

    # 5. Confirm deleted
    re_get = await async_client.get(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert re_get.status_code == 404


async def test_list_returns_only_own_medications(async_client: AsyncClient):
    """Verify listing medications returns only those of the requesting patient."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates 2 medications
    await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Aspirin", "status": "active"},
    )
    await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Lisinopril", "status": "active"},
    )

    # User B creates 1 medication
    await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Atorvastatin", "status": "active"},
    )

    # Check User A's list
    list_a = await async_client.get(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    names_a = [m["name"] for m in list_a.json()]
    assert "Aspirin" in names_a
    assert "Lisinopril" in names_a
    assert "Atorvastatin" not in names_a

    # Check User B's list
    list_b = await async_client.get(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    names_b = [m["name"] for m in list_b.json()]
    assert names_b == ["Atorvastatin"]


async def test_cross_user_isolation_returns_403(async_client: AsyncClient):
    """Verify unauthorized access to another user's medication returns 403."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates medication
    res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Confidential Med", "status": "active"},
    )
    med_id = res.json()["id"]

    # User B attempts GET -> 403
    get_res = await async_client.get(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 403
    assert get_res.json()["detail"] == "Not authorized to access this resource"

    # User B attempts PATCH -> 403
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Hacked Name"},
    )
    assert patch_res.status_code == 403

    # User B attempts DELETE -> 403
    del_res = await async_client.delete(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 403

    # Confirm medication still exists and unchanged for User A
    check_res = await async_client.get(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert check_res.status_code == 200
    assert check_res.json()["name"] == "Confidential Med"


async def test_temporal_fields_stored_and_returned(async_client: AsyncClient):
    """Verify started_at, ended_at, and recorded_at fields."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Prednisone",
        "status": "stopped",
        "started_at": "2023-06-01",
        "ended_at": "2023-06-14",
    }
    create_res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["started_at"] == "2023-06-01"
    assert data["ended_at"] == "2023-06-14"
    med_id = data["id"]

    # Update ended_at — started_at must remain unchanged
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"ended_at": "2023-07-01"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["ended_at"] == "2023-07-01"
    assert patch_res.json()["started_at"] == "2023-06-01"  # preserved


async def test_status_transition(async_client: AsyncClient):
    """Verify status can be transitioned from active to stopped."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    create_res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Omeprazole", "status": "active"},
    )
    assert create_res.status_code == 201
    med_id = create_res.json()["id"]
    assert create_res.json()["status"] == "active"

    # Transition to stopped
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "stopped"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "stopped"

    # Verify via GET
    get_res = await async_client.get(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "stopped"


async def test_invalid_status_returns_422(async_client: AsyncClient):
    """Verify invalid status value returns 422 Unprocessable Entity."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "SomeMed", "status": "discontinued"},
    )
    assert res.status_code == 422


async def test_non_existent_medication_returns_404(async_client: AsyncClient):
    """Verify accessing a non-existent medication ID returns 404."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    random_id = str(uuid.uuid4())

    get_res = await async_client.get(
        f"/api/v1/medications/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 404

    patch_res = await async_client.patch(
        f"/api/v1/medications/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "New Name"},
    )
    assert patch_res.status_code == 404

    del_res = await async_client.delete(
        f"/api/v1/medications/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 404


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    random_id = str(uuid.uuid4())

    res1 = await async_client.get("/api/v1/medications")
    assert res1.status_code == 401

    res2 = await async_client.post(
        "/api/v1/medications",
        json={"name": "Test", "status": "active"},
    )
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/medications/{random_id}")
    assert res3.status_code == 401

    res4 = await async_client.patch(
        f"/api/v1/medications/{random_id}",
        json={"name": "Test"},
    )
    assert res4.status_code == 401

    res5 = await async_client.delete(f"/api/v1/medications/{random_id}")
    assert res5.status_code == 401


async def test_provenance_assigned_server_side(async_client: AsyncClient):
    """Verify source_type is assigned server-side as PATIENT_REPORTED.

    Client-supplied source_type must not override server-side provenance.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Normal create — source_type must be PATIENT_REPORTED
    res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Metoprolol", "status": "active"},
    )
    assert res.status_code == 201
    assert res.json()["source_type"] == "PATIENT_REPORTED"
    med_id = res.json()["id"]

    # 2. Create with client-supplied source_type (extra field, ignored by schema)
    res_fake = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Warfarin",
            "status": "active",
            "source_type": "CLINICIAN_CONFIRMED",
        },
    )
    assert res_fake.status_code == 201
    assert res_fake.json()["source_type"] == "PATIENT_REPORTED"

    # 3. Attempt to PATCH source_type (extra field, ignored by schema)
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_type": "SOURCE_DOCUMENT"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["source_type"] == "PATIENT_REPORTED"


async def test_as_needed_field(async_client: AsyncClient):
    """Verify as_needed boolean field is stored and updated correctly."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # Create with as_needed=True
    create_res = await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Albuterol", "status": "active", "as_needed": True},
    )
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["as_needed"] is True
    med_id = data["id"]

    # Update to as_needed=False
    patch_res = await async_client.patch(
        f"/api/v1/medications/{med_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"as_needed": False},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["as_needed"] is False
