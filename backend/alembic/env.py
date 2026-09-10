import asyncio
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.db import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model's MetaData object for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url or "driver://user:pass" in url:
        return settings.DATABASE_URL
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations online using an async engine."""
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        if isinstance(connectable, Connection):
            do_run_migrations(connectable)
            return
        await connectable.run_sync(do_run_migrations)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        if isinstance(connectable, Connection):
            do_run_migrations(connectable)
            return
        asyncio.run(connectable.run_sync(do_run_migrations))
        return

    url = get_url()
    # If the URL is synchronous (e.g. SQLite for tests), run with sync engine
    is_async = "+async" in url or "+aiosqlite" in url or "asyncpg" in url
    if not is_async:
        section = config.get_section(config.config_ini_section, {})
        section["sqlalchemy.url"] = url
        connectable = engine_from_config(
            section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            do_run_migrations(connection)
        connectable.dispose()
        return

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
