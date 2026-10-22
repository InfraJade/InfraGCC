"""Alembic environment (async, asyncpg).

Migrations run as the schema owner: MIGRATION_DATABASE_URL, falling back to DATABASE_URL.
TimescaleDB statements that cannot run inside a transaction use `op.get_context().autocommit_block()`.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.attributes.get("database_url")
    if isinstance(override, str):
        return override
    explicit = os.environ.get("MIGRATION_DATABASE_URL")
    if explicit:
        return explicit
    settings = get_settings()
    if settings.migration_database_url is not None:
        return settings.migration_database_url.get_secret_value()
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
