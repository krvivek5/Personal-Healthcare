import uuid

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_create_condition_and_defaults(async_client: AsyncClient):
    """Verify condition creation and default source_type=PATIENT_REPORTED."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Hypertension",
        "status": "active",
        "is_chronic": True,
        "notes": "Diagnosed during routine exam",
    }
    response = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["name"] == "Hypertension"
    assert data["status"] == "active"
    assert data["is_chronic"] is True
    assert data["notes"] == "Diagnosed during routine exam"
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
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Asthma",
            "status": "active",
            "is_chronic": True,
        },
    )
    assert create_res.status_code == 201
    cond_id = create_res.json()["id"]

    # 2. Read (get by ID)
    get_res = await async_client.get(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Asthma"
    assert get_res.json()["status"] == "active"

    # 3. Update (patch)
    patch_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "resolved",
            "notes": "Symptoms well managed",
        },
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["status"] == "resolved"
    assert updated_data["notes"] == "Symptoms well managed"
    assert updated_data["is_chronic"] is True  # preserved

    # 4. Delete
    delete_res = await async_client.delete(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_res.status_code == 204

    # 5. Confirm deleted
    re_get = await async_client.get(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert re_get.status_code == 404


async def test_list_returns_only_own_conditions(async_client: AsyncClient):
    """Verify listing conditions returns only those of the requesting patient."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates 2 conditions
    await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Type 2 Diabetes", "status": "active"},
    )
    await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Migraine", "status": "active"},
    )

    # User B creates 1 condition
    await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Eczema", "status": "active"},
    )

    # Check User A's list
    list_a = await async_client.get(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    names_a = [c["name"] for c in list_a.json()]
    assert "Type 2 Diabetes" in names_a
    assert "Migraine" in names_a
    assert "Eczema" not in names_a

    # Check User B's list
    list_b = await async_client.get(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    names_b = [c["name"] for c in list_b.json()]
    assert names_b == ["Eczema"]


async def test_cross_user_isolation_returns_403(async_client: AsyncClient):
    """Verify unauthorized access to another user's condition returns 403."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates condition
    res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Confidential Condition", "status": "active"},
    )
    cond_id = res.json()["id"]

    # User B attempts GET -> 403
    get_res = await async_client.get(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 403
    assert get_res.json()["detail"] == "Not authorized to access this resource"

    # User B attempts PATCH -> 403
    patch_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Hacked Name"},
    )
    assert patch_res.status_code == 403

    # User B attempts DELETE -> 403
    del_res = await async_client.delete(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 403

    # Confirm condition still exists and unchanged for User A
    check_res = await async_client.get(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert check_res.status_code == 200
    assert check_res.json()["name"] == "Confidential Condition"


async def test_temporal_fields_stored_and_returned(async_client: AsyncClient):
    """Verify started_at, ended_at, and recorded_at fields."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Seasonal Allergies",
        "status": "resolved",
        "is_chronic": False,
        "started_at": "2021-03-01",
        "ended_at": "2021-06-01",
    }
    create_res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["started_at"] == "2021-03-01"
    assert data["ended_at"] == "2021-06-01"
    cond_id = data["id"]

    # Update ended_at
    patch_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"ended_at": "2021-07-01"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["ended_at"] == "2021-07-01"
    assert patch_res.json()["started_at"] == "2021-03-01"


async def test_invalid_status_returns_422(async_client: AsyncClient):
    """Verify invalid status value returns 422 Unprocessable Entity."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # Status 'chronic' is invalid (chronicity is captured by is_chronic)
    res1 = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Arthritis", "status": "chronic"},
    )
    assert res1.status_code == 422

    # Status 'unknown' is invalid
    res2 = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Arthritis", "status": "unknown"},
    )
    assert res2.status_code == 422


async def test_non_existent_condition_returns_404(async_client: AsyncClient):
    """Verify accessing a non-existent condition ID returns 404."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    random_id = str(uuid.uuid4())

    get_res = await async_client.get(
        f"/api/v1/conditions/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 404

    patch_res = await async_client.patch(
        f"/api/v1/conditions/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "New Name"},
    )
    assert patch_res.status_code == 404

    del_res = await async_client.delete(
        f"/api/v1/conditions/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 404


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    random_id = str(uuid.uuid4())

    res1 = await async_client.get("/api/v1/conditions")
    assert res1.status_code == 401

    res2 = await async_client.post(
        "/api/v1/conditions",
        json={"name": "Test", "status": "active"},
    )
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/conditions/{random_id}")
    assert res3.status_code == 401

    res4 = await async_client.patch(
        f"/api/v1/conditions/{random_id}",
        json={"name": "Test"},
    )
    assert res4.status_code == 401

    res5 = await async_client.delete(f"/api/v1/conditions/{random_id}")
    assert res5.status_code == 401


async def test_provenance_assigned_server_side(async_client: AsyncClient):
    """Verify source_type is assigned server-side as PATIENT_REPORTED.

    Client-supplied source_type must not override server-side provenance.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Normal create without source_type in schema
    res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Hypertension", "status": "active"},
    )
    assert res.status_code == 201
    assert res.json()["source_type"] == "PATIENT_REPORTED"
    cond_id = res.json()["id"]

    # 2. Attempt to create with restricted client-supplied source_type
    res_fake = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Diabetes",
            "status": "active",
            "source_type": "CLINICIAN_CONFIRMED",
        },
    )
    assert res_fake.status_code == 422

    # 3. Attempt to update with restricted client-supplied source_type
    patch_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_type": "CLINICIAN_CONFIRMED"},
    )
    assert patch_res.status_code == 422


async def test_verification_state_returns_422(async_client: AsyncClient):
    """
    Verify that submitting verification_state in Create/Update payloads returns 422.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Attempt Create with verification_state
    create_res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Diabetes",
            "status": "active",
            "verification_state": "PATIENT_REPORTED",
        },
    )
    assert create_res.status_code == 422

    # 2. Create a valid condition to test Update
    valid_create_res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Diabetes", "status": "active"},
    )
    assert valid_create_res.status_code == 201
    cond_id = valid_create_res.json()["id"]

    # 3. Attempt Update with verification_state
    update_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"verification_state": "PATIENT_REPORTED"},
    )
    assert update_res.status_code == 422
