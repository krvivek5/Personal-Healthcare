from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all domain models."""

    pass


from app.db.session import (  # noqa: E402
    async_session_factory,
    engine,
    get_db,
    get_db_context,
)

__all__ = [
    "Base",
    "engine",
    "async_session_factory",
    "get_db",
    "get_db_context",
]
