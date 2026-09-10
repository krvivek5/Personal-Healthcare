from unittest.mock import AsyncMock, patch

import pytest
from fastapi import APIRouter, Depends, HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import settings
from app.db.base import (
    async_session_factory,
    engine,
    get_db,
    get_db_context,
)
from app.main import app


def test_engine_configuration():
    """Verify the SQLAlchemy async engine is properly configured."""
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    expected_url = settings.DATABASE_URL
    assert engine.url.render_as_string(hide_password=False) == expected_url


@pytest.mark.asyncio
async def test_session_factory_configuration():
    """Verify the async session factory creates configured AsyncSessions."""
    assert isinstance(async_session_factory, async_sessionmaker)
    session = async_session_factory()
    try:
        assert isinstance(session, AsyncSession)
        assert session.bind == engine
        assert session.sync_session.expire_on_commit is False
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_database_connection_lifecycle():
    """Verify connection checkout and release through the async engine."""
    conn = engine.connect()
    assert isinstance(conn, AsyncConnection)
    assert conn.engine == engine

    with (
        patch.object(AsyncConnection, "start", new_callable=AsyncMock) as mock_start,
        patch.object(AsyncConnection, "close", new_callable=AsyncMock) as mock_close,
    ):
        mock_start.return_value = conn
        async with conn as checked_out:
            assert checked_out is conn

        mock_start.assert_awaited_once()
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_yields_session_and_closes_on_completion():
    """Verify get_db generator yields an AsyncSession and closes on exit."""
    real_session = async_session_factory()
    with patch.object(real_session, "close", wraps=real_session.close) as mock_close:
        with patch("app.db.session.async_session_factory", return_value=real_session):
            yielded_session = None
            async for session in get_db():
                yielded_session = session
                assert isinstance(session, AsyncSession)
                assert session is real_session

            assert yielded_session is not None
        mock_close.assert_awaited()


@pytest.mark.asyncio
async def test_get_db_closes_session_on_generator_throw():
    """Verify get_db closes session when an exception is thrown into it."""
    real_session = async_session_factory()
    with patch.object(real_session, "close", wraps=real_session.close) as mock_close:
        with patch("app.db.session.async_session_factory", return_value=real_session):
            gen = get_db()
            session = await anext(gen)
            assert session is real_session
            with pytest.raises(RuntimeError, match="Consumer failure"):
                await gen.athrow(RuntimeError("Consumer failure"))

        mock_close.assert_awaited()


@pytest.mark.asyncio
async def test_get_db_closes_session_on_generator_aclose():
    """Verify get_db generator closes session when generator is closed early."""
    real_session = async_session_factory()
    with patch.object(real_session, "close", wraps=real_session.close) as mock_close:
        with patch("app.db.session.async_session_factory", return_value=real_session):
            gen = get_db()
            session = await anext(gen)
            assert session is real_session
            await gen.aclose()

        mock_close.assert_awaited()


@pytest.mark.asyncio
async def test_get_db_context_lifecycle():
    """Verify get_db_context async context manager opens and closes session."""
    real_session = async_session_factory()
    with patch.object(real_session, "close", wraps=real_session.close) as mock_close:
        with patch("app.db.session.async_session_factory", return_value=real_session):
            async with get_db_context() as session:
                assert session is real_session

        mock_close.assert_awaited()


@pytest.mark.asyncio
async def test_get_db_context_closes_on_exception():
    """Verify get_db_context closes session on exception."""
    real_session = async_session_factory()
    with patch.object(real_session, "close", wraps=real_session.close) as mock_close:
        with patch("app.db.session.async_session_factory", return_value=real_session):
            with pytest.raises(ValueError, match="Context error"):
                async with get_db_context() as session:
                    assert session is real_session
                    raise ValueError("Context error")

        mock_close.assert_awaited()


@pytest.mark.asyncio
async def test_fastapi_request_scoped_session_closed_after_success(
    async_client: AsyncClient,
):
    """Verify route using Depends(get_db) closes session after success."""
    test_router = APIRouter()
    captured_session = None

    @test_router.get("/_test_m3/db-success")
    async def endpoint_success(db: AsyncSession = Depends(get_db)):
        nonlocal captured_session
        captured_session = db
        return {"status": "success"}

    app.include_router(test_router)
    try:
        real_session = async_session_factory()
        with patch.object(
            real_session, "close", wraps=real_session.close
        ) as mock_close:
            with patch(
                "app.db.session.async_session_factory",
                return_value=real_session,
            ):
                response = await async_client.get("/_test_m3/db-success")
                assert response.status_code == 200
                assert response.json() == {"status": "success"}
                assert captured_session is real_session
            mock_close.assert_awaited()
    finally:
        app.routes[:] = [
            r for r in app.routes if getattr(r, "path", None) != "/_test_m3/db-success"
        ]


@pytest.mark.asyncio
async def test_fastapi_request_scoped_session_closed_after_http_exception(
    async_client: AsyncClient,
):
    """Verify route using Depends(get_db) closes session after HTTPException."""
    test_router = APIRouter()

    @test_router.get("/_test_m3/db-http-error")
    async def endpoint_http_error(db: AsyncSession = Depends(get_db)):
        raise HTTPException(status_code=400, detail="Invalid request")

    app.include_router(test_router)
    try:
        real_session = async_session_factory()
        with patch.object(
            real_session, "close", wraps=real_session.close
        ) as mock_close:
            with patch(
                "app.db.session.async_session_factory",
                return_value=real_session,
            ):
                response = await async_client.get("/_test_m3/db-http-error")
                assert response.status_code == 400
                assert response.json()["detail"] == "Invalid request"
            mock_close.assert_awaited()
    finally:
        app.routes[:] = [
            r
            for r in app.routes
            if getattr(r, "path", None) != "/_test_m3/db-http-error"
        ]


@pytest.mark.asyncio
async def test_fastapi_request_scoped_session_closed_after_unhandled_exception(
    async_client: AsyncClient,
):
    """Verify route using Depends(get_db) closes session on unhandled error."""
    test_router = APIRouter()

    @test_router.get("/_test_m3/db-unhandled-error")
    async def endpoint_unhandled_error(db: AsyncSession = Depends(get_db)):
        raise RuntimeError("Internal unexpected error")

    app.include_router(test_router)
    try:
        real_session = async_session_factory()
        with patch.object(
            real_session, "close", wraps=real_session.close
        ) as mock_close:
            with patch(
                "app.db.session.async_session_factory",
                return_value=real_session,
            ):
                with pytest.raises(RuntimeError, match="Internal unexpected error"):
                    await async_client.get("/_test_m3/db-unhandled-error")
            mock_close.assert_awaited()
    finally:
        app.routes[:] = [
            r
            for r in app.routes
            if getattr(r, "path", None) != "/_test_m3/db-unhandled-error"
        ]
