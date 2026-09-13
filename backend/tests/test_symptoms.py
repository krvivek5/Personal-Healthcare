import uuid

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_create_symptom_and_defaults(async_client: AsyncClient):
    """Verify symptom creation and default source_type=PATIENT_REPORTED."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Headache",
        "severity": "moderate",
        "notes": "Worse in the morning",
    }
    response = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["name"] == "Headache"
    assert data["severity"] == "moderate"
    assert data["notes"] == "Worse in the morning"
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
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Fatigue",
            "severity": "mild",
        },
    )
    assert create_res.status_code == 201
    sym_id = create_res.json()["id"]

    # 2. Read (get by ID)
    get_res = await async_client.get(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Fatigue"
    assert get_res.json()["severity"] == "mild"

    # 3. Update (patch)
    patch_res = await async_client.patch(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "severity": "severe",
            "notes": "Getting worse",
        },
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["severity"] == "severe"
    assert updated_data["notes"] == "Getting worse"
    assert updated_data["name"] == "Fatigue"  # preserved

    # 4. Delete
    delete_res = await async_client.delete(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_res.status_code == 204

    # 5. Confirm deleted
    re_get = await async_client.get(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert re_get.status_code == 404


async def test_list_returns_only_own_symptoms(async_client: AsyncClient):
    """Verify listing symptoms returns only those of the requesting patient."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates 2 symptoms
    await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Nausea", "severity": "mild"},
    )
    await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Dizziness"},
    )

    # User B creates 1 symptom
    await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Back Pain", "severity": "severe"},
    )

    # Check User A's list
    list_a = await async_client.get(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    names_a = [s["name"] for s in list_a.json()]
    assert "Nausea" in names_a
    assert "Dizziness" in names_a
    assert "Back Pain" not in names_a

    # Check User B's list
    list_b = await async_client.get(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    names_b = [s["name"] for s in list_b.json()]
    assert names_b == ["Back Pain"]


async def test_cross_user_isolation_returns_403(async_client: AsyncClient):
    """Verify unauthorized access to another user's symptom returns 403."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates symptom
    res = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Confidential Symptom", "severity": "severe"},
    )
    sym_id = res.json()["id"]

    # User B attempts GET -> 403
    get_res = await async_client.get(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 403
    assert get_res.json()["detail"] == "Not authorized to access this resource"

    # User B attempts PATCH -> 403
    patch_res = await async_client.patch(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"name": "Hacked Name"},
    )
    assert patch_res.status_code == 403

    # User B attempts DELETE -> 403
    del_res = await async_client.delete(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 403

    # Confirm symptom still exists and unchanged for User A
    check_res = await async_client.get(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert check_res.status_code == 200
    assert check_res.json()["name"] == "Confidential Symptom"


async def test_temporal_fields_stored_and_returned(async_client: AsyncClient):
    """Verify started_at, ended_at, and recorded_at fields."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "name": "Seasonal Cough",
        "severity": "mild",
        "started_at": "2023-11-01",
        "ended_at": "2023-11-20",
    }
    create_res = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["started_at"] == "2023-11-01"
    assert data["ended_at"] == "2023-11-20"
    sym_id = data["id"]

    # Update ended_at
    patch_res = await async_client.patch(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"ended_at": "2023-12-01"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["ended_at"] == "2023-12-01"
    assert patch_res.json()["started_at"] == "2023-11-01"  # preserved


async def test_invalid_severity_returns_422(async_client: AsyncClient):
    """Verify invalid severity value returns 422 Unprocessable Entity."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    res = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Headache", "severity": "extreme"},
    )
    assert res.status_code == 422


async def test_non_existent_symptom_returns_404(async_client: AsyncClient):
    """Verify accessing a non-existent symptom ID returns 404."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    random_id = str(uuid.uuid4())

    get_res = await async_client.get(
        f"/api/v1/symptoms/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 404

    patch_res = await async_client.patch(
        f"/api/v1/symptoms/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "New Name"},
    )
    assert patch_res.status_code == 404

    del_res = await async_client.delete(
        f"/api/v1/symptoms/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 404


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    random_id = str(uuid.uuid4())

    res1 = await async_client.get("/api/v1/symptoms")
    assert res1.status_code == 401

    res2 = await async_client.post(
        "/api/v1/symptoms",
        json={"name": "Test"},
    )
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/symptoms/{random_id}")
    assert res3.status_code == 401

    res4 = await async_client.patch(
        f"/api/v1/symptoms/{random_id}",
        json={"name": "Test"},
    )
    assert res4.status_code == 401

    res5 = await async_client.delete(f"/api/v1/symptoms/{random_id}")
    assert res5.status_code == 401


async def test_provenance_assigned_server_side(async_client: AsyncClient):
    """Verify source_type is assigned server-side as PATIENT_REPORTED.

    Client-supplied source_type must not override server-side provenance.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Normal create without source_type in schema
    res = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Insomnia"},
    )
    assert res.status_code == 201
    assert res.json()["source_type"] == "PATIENT_REPORTED"
    sym_id = res.json()["id"]

    # 2. Attempt to create with restricted client-supplied source_type
    res_fake = await async_client.post(
        "/api/v1/symptoms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Fatigue",
            "source_type": "CLINICIAN_CONFIRMED",
        },
    )
    assert res_fake.status_code == 422

    # 3. Attempt to update with restricted client-supplied source_type
    patch_res = await async_client.patch(
        f"/api/v1/symptoms/{sym_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_type": "CLINICIAN_CONFIRMED"},
    )
    assert patch_res.status_code == 422
