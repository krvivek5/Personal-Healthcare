import uuid

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def test_create_goal_and_defaults(async_client: AsyncClient):
    """Verify goal creation and default field values."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    payload = {
        "description": "Run a 5K without stopping",
        "status": "active",
        "notes": "Training three times a week",
    }
    response = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["patient_id"] is not None
    assert data["description"] == "Run a 5K without stopping"
    assert data["status"] == "active"
    assert data["notes"] == "Training three times a week"
    assert data["target_date"] is None
    assert data["recorded_at"] is not None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None
    # Goals have no source_type
    assert "source_type" not in data


async def test_crud_lifecycle(async_client: AsyncClient):
    """Verify full CRUD lifecycle: create, read, update, delete."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # 1. Create
    create_res = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "description": "Reduce sugar intake",
            "status": "active",
            "target_date": "2027-01-01",
        },
    )
    assert create_res.status_code == 201
    goal_id = create_res.json()["id"]
    assert create_res.json()["target_date"] == "2027-01-01"

    # 2. Read (get by ID)
    get_res = await async_client.get(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["description"] == "Reduce sugar intake"
    assert get_res.json()["status"] == "active"

    # 3. Update (patch) — change status to achieved
    patch_res = await async_client.patch(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "achieved",
            "notes": "Completed ahead of schedule",
        },
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["status"] == "achieved"
    assert updated["notes"] == "Completed ahead of schedule"
    assert updated["description"] == "Reduce sugar intake"  # preserved
    assert updated["target_date"] == "2027-01-01"  # preserved

    # 4. Delete
    delete_res = await async_client.delete(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_res.status_code == 204

    # 5. Confirm deleted
    re_get = await async_client.get(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert re_get.status_code == 404


async def test_status_transitions(async_client: AsyncClient):
    """Verify all valid status values: active, achieved, abandoned."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    for status_val in ("active", "achieved", "abandoned"):
        res = await async_client.post(
            "/api/v1/goals",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "description": f"Goal with status {status_val}",
                "status": status_val,
            },
        )
        assert res.status_code == 201
        assert res.json()["status"] == status_val


async def test_list_returns_only_own_goals(async_client: AsyncClient):
    """Verify listing goals returns only those of the requesting patient."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates 2 goals
    await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"description": "Goal A1", "status": "active"},
    )
    await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"description": "Goal A2", "status": "active"},
    )

    # User B creates 1 goal
    await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"description": "Goal B1", "status": "active"},
    )

    # User A's list should have only A1 and A2
    list_a = await async_client.get(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    descs_a = [g["description"] for g in list_a.json()]
    assert "Goal A1" in descs_a
    assert "Goal A2" in descs_a
    assert "Goal B1" not in descs_a

    # User B's list should have only B1
    list_b = await async_client.get(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    descs_b = [g["description"] for g in list_b.json()]
    assert descs_b == ["Goal B1"]


async def test_cross_user_isolation_returns_403(async_client: AsyncClient):
    """Verify unauthorized access to another user's goal returns 403."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    token_a = create_test_token(user_id=user_a)
    token_b = create_test_token(user_id=user_b)

    # User A creates a goal
    res = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"description": "User A private goal", "status": "active"},
    )
    goal_id = res.json()["id"]

    # User B GET -> 403
    get_res = await async_client.get(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 403
    assert get_res.json()["detail"] == "Not authorized to access this resource"

    # User B PATCH -> 403
    patch_res = await async_client.patch(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"description": "Hijacked goal"},
    )
    assert patch_res.status_code == 403

    # User B DELETE -> 403
    del_res = await async_client.delete(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 403

    # Goal still intact for User A
    check = await async_client.get(
        f"/api/v1/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert check.status_code == 200
    assert check.json()["description"] == "User A private goal"


async def test_invalid_status_returns_422(async_client: AsyncClient):
    """Verify invalid status value returns 422 Unprocessable Entity."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    res = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token}"},
        json={"description": "Bad status goal", "status": "completed"},
    )
    assert res.status_code == 422


async def test_missing_required_fields_returns_422(async_client: AsyncClient):
    """Verify that missing required fields (description, status) returns 422."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    # Missing status
    res1 = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token}"},
        json={"description": "No status"},
    )
    assert res1.status_code == 422

    # Missing description
    res2 = await async_client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "active"},
    )
    assert res2.status_code == 422


async def test_non_existent_goal_returns_404(async_client: AsyncClient):
    """Verify accessing a non-existent goal returns 404."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    random_id = str(uuid.uuid4())

    get_res = await async_client.get(
        f"/api/v1/goals/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 404

    patch_res = await async_client.patch(
        f"/api/v1/goals/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "achieved"},
    )
    assert patch_res.status_code == 404

    del_res = await async_client.delete(
        f"/api/v1/goals/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 404


async def test_unauthenticated_requests_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    random_id = str(uuid.uuid4())

    res1 = await async_client.get("/api/v1/goals")
    assert res1.status_code == 401

    res2 = await async_client.post(
        "/api/v1/goals",
        json={"description": "Test", "status": "active"},
    )
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/goals/{random_id}")
    assert res3.status_code == 401

    res4 = await async_client.patch(
        f"/api/v1/goals/{random_id}",
        json={"status": "achieved"},
    )
    assert res4.status_code == 401

    res5 = await async_client.delete(f"/api/v1/goals/{random_id}")
    assert res5.status_code == 401
