import base64
import time
from typing import Optional

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from jwt import PyJWKClient

from app.core.auth import set_jwks_client
from app.core.config import settings

# Test EC key pair for generating and verifying test JWTs
TEST_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()
TEST_KID = "test-key-id-123"

# Distinct key pair for testing invalid/tampered signatures
UNTRUSTED_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


def int_to_b64(val: int, length: int = 32) -> str:
    b = val.to_bytes(length, "big")
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def get_test_jwk(kid: str = TEST_KID, public_key=TEST_PUBLIC_KEY) -> dict:
    pn = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "use": "sig",
        "kid": kid,
        "x": int_to_b64(pn.x),
        "y": int_to_b64(pn.y),
    }


def create_test_token(
    user_id: str,
    email: Optional[str] = None,
    is_anonymous: bool = False,
    expires_in: int = 3600,
    private_key=TEST_PRIVATE_KEY,
    kid: Optional[str] = TEST_KID,
    issuer: Optional[str] = None,
    audience: str = "authenticated",
    algorithm: str = "ES256",
) -> str:
    """Helper to generate JWT tokens mimicking Supabase Auth tokens for testing."""
    payload = {
        "sub": user_id,
        "aud": audience,
        "iss": issuer or settings.supabase_issuer,
        "role": "authenticated",
        "is_anonymous": is_anonymous,
        "app_metadata": {
            "provider": "anonymous" if is_anonymous else "email",
            "providers": ["anonymous"] if is_anonymous else ["email"],
        },
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    if email:
        payload["email"] = email

    headers = {"typ": "JWT", "alg": algorithm}
    if kid is not None:
        headers["kid"] = kid

    if algorithm == "ES256":
        return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    else:
        # For testing invalid algorithms like HS256
        dummy_secret = "some-secret-string-at-least-32-chars!!"
        return jwt.encode(payload, dummy_secret, algorithm=algorithm, headers=headers)


@pytest.fixture(autouse=True)
def setup_test_jwks():
    """Configure mock in-memory JWKS client for test execution."""
    client = PyJWKClient(
        settings.supabase_jwks_url,
        cache_jwk_set=False,
    )
    client.fetch_data = lambda: {"keys": [get_test_jwk()]}
    set_jwks_client(client)
    yield client
    set_jwks_client(None)


@pytest.mark.asyncio
async def test_auth_me_anonymous_user(async_client: AsyncClient):
    """Verify backend accepts valid anonymous ES256 token with is_anonymous=True."""
    token = create_test_token(user_id="anon-user-123", is_anonymous=True)
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "anon-user-123"
    assert data["is_anonymous"] is True
    assert data["email"] is None


@pytest.mark.asyncio
async def test_auth_me_permanent_user(async_client: AsyncClient):
    """Verify backend accepts valid permanent user ES256 token."""
    token = create_test_token(
        user_id="perm-user-456",
        email="patient@example.com",
        is_anonymous=False,
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "perm-user-456"
    assert data["is_anonymous"] is False
    assert data["email"] == "patient@example.com"


@pytest.mark.asyncio
async def test_auth_unauthenticated_rejected(async_client: AsyncClient):
    """Verify unauthenticated requests are rejected with 401."""
    response = await async_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_auth_expired_token_rejected(async_client: AsyncClient):
    """Verify expired token is rejected with 401."""
    expired_token = create_test_token(
        user_id="user-expired",
        expires_in=-100,  # Expired in past
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auth_tampered_token_rejected(async_client: AsyncClient):
    """Verify token signed with untrusted key is rejected with 401."""
    token = create_test_token(
        user_id="user-invalid",
        private_key=UNTRUSTED_PRIVATE_KEY,
        kid=TEST_KID,
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "credentials" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auth_wrong_issuer_rejected(async_client: AsyncClient):
    """Verify token with valid signature but mismatched issuer is rejected with 401."""
    token = create_test_token(
        user_id="user-wrong-iss",
        issuer="https://other-project.supabase.co/auth/v1",
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "issuer" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auth_wrong_audience_rejected(async_client: AsyncClient):
    """Verify token with valid signature but wrong audience is rejected with 401."""
    token = create_test_token(
        user_id="user-wrong-aud",
        audience="other_audience",
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "audience" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auth_missing_kid_rejected(async_client: AsyncClient):
    """Verify token without kid header is rejected with 401."""
    token = create_test_token(
        user_id="user-no-kid",
        kid=None,
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "kid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auth_unknown_kid_rejected(async_client: AsyncClient):
    """Verify token with unknown kid is rejected with 401."""
    token = create_test_token(
        user_id="user-unknown-kid",
        kid="unknown-nonexistent-kid",
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    detail = response.json()["detail"].lower()
    assert "unknown" in detail or "signing key" in detail


@pytest.mark.asyncio
async def test_auth_invalid_algorithm_rejected(async_client: AsyncClient):
    """Verify token signed with unsupported algorithm is rejected with 401."""
    token = create_test_token(
        user_id="user-hs256",
        algorithm="HS256",
    )
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "algorithm" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_isolation_between_anonymous_users(async_client: AsyncClient):
    """Verify Anonymous User A cannot access Anonymous User B's data."""
    token_a = create_test_token(user_id="anon-a", is_anonymous=True)
    token_b = create_test_token(user_id="anon-b", is_anonymous=True)

    # User A creates item
    create_resp = await async_client.post(
        "/api/v1/workspace/items",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Private Note A", "content": "Confidential note A"},
    )
    assert create_resp.status_code == 201
    item_a = create_resp.json()

    # User A can read their own workspace
    resp_a = await async_client.get(
        "/api/v1/workspace",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 200
    assert any(it["id"] == item_a["id"] for it in resp_a.json())

    # User B reading their workspace cannot see User A's item
    resp_b = await async_client.get(
        "/api/v1/workspace",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200
    assert not any(it["id"] == item_a["id"] for it in resp_b.json())

    # User B attempting direct access to User A's item is forbidden (403)
    direct_resp = await async_client.get(
        f"/api/v1/workspace/items/{item_a['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert direct_resp.status_code == 403


@pytest.mark.asyncio
async def test_progressive_account_conversion_identity_continuity(
    async_client: AsyncClient,
):
    """Verify converting an anonymous identity to permanent retains user_id."""
    user_id = "progressive-user-789"

    # Step 1: User starts as Anonymous
    anon_token = create_test_token(user_id=user_id, is_anonymous=True)
    create_resp = await async_client.post(
        "/api/v1/workspace/items",
        headers={"Authorization": f"Bearer {anon_token}"},
        json={"title": "Initial Observation", "content": "Recorded anonymously"},
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    # Step 2: User converts to permanent account (same user_id, now with email)
    perm_token = create_test_token(
        user_id=user_id,
        email="converted.patient@example.com",
        is_anonymous=False,
    )

    # Step 3: Converted permanent user verifies their identity details
    me_resp = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {perm_token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["id"] == user_id  # Unbroken user_id!
    assert me_data["is_anonymous"] is False
    assert me_data["email"] == "converted.patient@example.com"

    # Step 4: Converted user retains access to item created during anon session
    read_resp = await async_client.get(
        f"/api/v1/workspace/items/{item_id}",
        headers={"Authorization": f"Bearer {perm_token}"},
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["title"] == "Initial Observation"

    # Step 5: Permanent User B cannot access Converted User A's data
    token_other = create_test_token(
        user_id="another-permanent-user",
        email="other@example.com",
        is_anonymous=False,
    )
    forbidden_resp = await async_client.get(
        f"/api/v1/workspace/items/{item_id}",
        headers={"Authorization": f"Bearer {token_other}"},
    )
    assert forbidden_resp.status_code == 403
