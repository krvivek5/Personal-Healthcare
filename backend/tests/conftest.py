import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jwt import PyJWKClient

from app.core.auth import set_jwks_client
from app.core.config import settings
from app.db.base import async_session_factory, engine
from app.main import app
from tests.test_auth import get_test_jwk


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


@pytest.fixture
async def async_client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
async def db():
    async with async_session_factory() as session:
        # Start a transaction so we can rollback after the test
        await session.begin()
        yield session
        await session.rollback()
    await engine.dispose()
