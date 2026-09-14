import asyncio
import contextlib
import uuid

from httpx import ASGITransport, AsyncClient
from jwt import PyJWKClient

from app.core.auth import set_jwks_client
from app.core.config import settings
from app.main import app
from tests.test_auth import create_test_token, get_test_jwk


@contextlib.asynccontextmanager
async def mock_jwks():
    client = PyJWKClient(
        settings.supabase_jwks_url,
        cache_jwk_set=False,
    )
    client.fetch_data = lambda: {"keys": [get_test_jwk()]}
    set_jwks_client(client)
    try:
        yield
    finally:
        set_jwks_client(None)


async def run_verification():
    async with mock_jwks():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Create user and setup data
            user_id = str(uuid.uuid4())
            token = create_test_token(user_id=user_id)

            # Setup data
            await client.post(
                "/api/v1/conditions",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Asthma", "status": "active", "is_chronic": True},
            )
            await client.post(
                "/api/v1/medications",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "Lisinopril",
                    "dosage": "10mg",
                    "status": "active",
                    "frequency": "daily",
                },
            )
            await client.post(
                "/api/v1/medications",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "Amoxicillin",
                    "dosage": "500mg",
                    "status": "stopped",
                    "frequency": "daily",
                    "ended_at": "2023-01-01",
                },
            )

            print("\n--- 1. SUFFICIENT ---")
            res1 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "What is my Lisinopril dosage?"},
            )
            print(f"Status: {res1.status_code}")
            print(f"Payload: {res1.json()}\n")

            print("--- 2. PARTIALLY_SUFFICIENT ---")
            res2 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "What is the clinic for my Lisinopril?"},
            )
            print(f"Status: {res2.status_code}")
            print(f"Payload: {res2.json()}\n")

            print("--- 3. INSUFFICIENT ---")
            res3 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "What is my blood type?"},
            )
            print(f"Status: {res3.status_code}")
            print(f"Payload: {res3.json()}\n")

            print("--- 4. CURRENT vs HISTORICAL ---")
            res4 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "What are my current medications?"},
            )
            print(f"Status: {res4.status_code}")
            print(f"Payload: {res4.json()}\n")

            print("--- 5. PROVENANCE ---")
            print(f"Citations in res1: {res1.json().get('citations')}\n")

            print("--- 6. CROSS-USER ISOLATION ---")
            user2_id = str(uuid.uuid4())
            token2 = create_test_token(user_id=user2_id)
            res6 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token2}"},
                json={"query": "What is my Lisinopril dosage?"},
            )
            print(f"Status: {res6.status_code}")
            print(f"Payload: {res6.json()}\n")

            print("--- 7. SAFETY ---")
            res7 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "I have severe crushing chest pain."},
            )
            print(f"Status: {res7.status_code}")
            print(f"Payload: {res7.json()}\n")

            print("--- 8. INVALID INPUT ---")
            res8 = await client.post(
                "/api/v1/health-inquiry",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "   "},
            )
            print(f"Status: {res8.status_code}")
            print(f"Payload: {res8.json()}\n")

            print("--- 9. UNAUTHENTICATED ---")
            res9 = await client.post(
                "/api/v1/health-inquiry",
                json={"query": "What medications am I taking?"},
            )
            print(f"Status: {res9.status_code}")
            print(f"Payload: {res9.json()}\n")


if __name__ == "__main__":
    asyncio.run(run_verification())
