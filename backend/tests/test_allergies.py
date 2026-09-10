import uuid

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_create_allergy_and_defaults(async_client: AsyncClient):
    """Verify allergy creation and default source_type=PATIENT_REPORTED."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "allergen": "Peanuts",
        "reaction": "Hives",
        "severity": "severe",
        "notes": "Carry EpiPen",
    }
    response = await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["allergen"] == "Peanuts"
    assert data["reaction"] == "Hives"
    assert data["severity"] == "severe"
    assert data["notes"] == "Carry EpiPen"
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
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "allergen": "Dust Mites",
            "reaction": "Sneezing",
            "severity": "mild",
        },
    )
    assert create_res.status_code == 201
    alg_id = create_res.json()["id"]

    # 2. Read (get by ID)
    get_res = await async_client.get(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["allergen"] == "Dust Mites"
    assert get_res.json()["reaction"] == "Sneezing"

    # 3. Update (patch)
    patch_res = await async_client.patch(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "severity": "moderate",
            "notes": "Getting worse in spring",
        },
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["severity"] == "moderate"
    assert updated_data["notes"] == "Getting worse in spring"
    assert updated_data["allergen"] == "Dust Mites"  # preserved
    assert updated_data["reaction"] == "Sneezing"  # preserved

    # 4. Delete
    delete_res = await async_client.delete(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_res.status_code == 204

    # 5. Confirm deleted
    re_get = await async_client.get(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert re_get.status_code == 404


async def test_list_returns_only_own_allergies(async_client: AsyncClient):
    """Verify listing allergies returns only those of the requesting patient."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates 2 allergies
    await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"allergen": "Pollen", "severity": "mild"},
    )
    await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"allergen": "Cats", "severity": "moderate"},
    )

    # User B creates 1 allergy
    await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"allergen": "Penicillin", "severity": "life_threatening"},
    )

    # Check User A's list
    list_a = await async_client.get(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    names_a = [a["allergen"] for a in list_a.json()]
    assert "Pollen" in names_a
    assert "Cats" in names_a
    assert "Penicillin" not in names_a

    # Check User B's list
    list_b = await async_client.get(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    names_b = [a["allergen"] for a in list_b.json()]
    assert names_b == ["Penicillin"]


async def test_cross_user_isolation_returns_403(async_client: AsyncClient):
    """Verify unauthorized access to another user's allergy returns 403."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates allergy
    res = await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"allergen": "Confidential Allergy", "severity": "severe"},
    )
    alg_id = res.json()["id"]

    # User B attempts GET -> 403
    get_res = await async_client.get(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 403
    assert get_res.json()["detail"] == "Not authorized to access this resource"

    # User B attempts PATCH -> 403
    patch_res = await async_client.patch(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"allergen": "Hacked Allergen"},
    )
    assert patch_res.status_code == 403

    # User B attempts DELETE -> 403
    del_res = await async_client.delete(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 403

    # Confirm allergy still exists and unchanged for User A
    check_res = await async_client.get(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert check_res.status_code == 200
    assert check_res.json()["allergen"] == "Confidential Allergy"


async def test_invalid_severity_returns_422(async_client: AsyncClient):
    """Verify invalid severity value returns 422 Unprocessable Entity."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    res = await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token}"},
        json={"allergen": "Dust", "severity": "extreme"},
    )
    assert res.status_code == 422


async def test_non_existent_allergy_returns_404(async_client: AsyncClient):
    """Verify accessing a non-existent allergy ID returns 404."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    random_id = str(uuid.uuid4())

    get_res = await async_client.get(
        f"/api/v1/allergies/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 404

    patch_res = await async_client.patch(
        f"/api/v1/allergies/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"allergen": "New Allergen"},
    )
    assert patch_res.status_code == 404

    del_res = await async_client.delete(
        f"/api/v1/allergies/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 404


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    random_id = str(uuid.uuid4())

    res1 = await async_client.get("/api/v1/allergies")
    assert res1.status_code == 401

    res2 = await async_client.post(
        "/api/v1/allergies",
        json={"allergen": "Test"},
    )
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/allergies/{random_id}")
    assert res3.status_code == 401

    res4 = await async_client.patch(
        f"/api/v1/allergies/{random_id}",
        json={"allergen": "Test"},
    )
    assert res4.status_code == 401

    res5 = await async_client.delete(f"/api/v1/allergies/{random_id}")
    assert res5.status_code == 401


async def test_provenance_assigned_server_side(async_client: AsyncClient):
    """Verify source_type is assigned server-side as PATIENT_REPORTED.

    Client-supplied source_type must not override server-side provenance.
    """
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Normal create — source_type must be PATIENT_REPORTED
    res = await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token}"},
        json={"allergen": "Latex"},
    )
    assert res.status_code == 201
    assert res.json()["source_type"] == "PATIENT_REPORTED"
    alg_id = res.json()["id"]

    # 2. Create with client-supplied source_type (extra field, ignored by schema)
    res_fake = await async_client.post(
        "/api/v1/allergies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "allergen": "Soy",
            "source_type": "CLINICIAN_CONFIRMED",
        },
    )
    assert res_fake.status_code == 201
    assert res_fake.json()["source_type"] == "PATIENT_REPORTED"

    # 3. Attempt to PATCH source_type (extra field, ignored by schema)
    patch_res = await async_client.patch(
        f"/api/v1/allergies/{alg_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_type": "SOURCE_DOCUMENT"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["source_type"] == "PATIENT_REPORTED"
