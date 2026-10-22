"""Test fixtures.

Database tests need a TimescaleDB server. TEST_DATABASE_URL points at a maintenance database on it
(default: the local dev container). A fresh `gcc_test` database is created and migrated once per session.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://gcc_owner:dev-owner-pw@localhost:5432/postgres"
)
TEST_DB = os.environ.get("TEST_DATABASE_NAME", "gcc_test")
TEST_ROLE_PASSWORD = "test-role-pw"

# Children first. Reference data written by migrations (metric definitions, built-in rules, global
# thresholds) is kept; everything else is wiped between tests.
_CLEANUP = [
    "DELETE FROM alert_activity",
    "DELETE FROM alerts",
    "DELETE FROM audit_log",
    "DELETE FROM users",
    "DELETE FROM app_settings",
    "DELETE FROM readings",
    "DELETE FROM latest_readings",
    "DELETE FROM health_status",
    "DELETE FROM events",
    "DELETE FROM bmc_thresholds",
    "DELETE FROM firmware_inventory",
    "DELETE FROM firmware_baselines",
    "DELETE FROM components",
    "DELETE FROM maintenance_windows",
    "DELETE FROM alert_routes",
    "DELETE FROM thresholds WHERE NOT (scope = 'global' AND updated_by = 'system')",
    "DELETE FROM alert_rules WHERE NOT builtin",
    "DELETE FROM servers",
    "DELETE FROM collectors",
    "DELETE FROM racks",
    "DELETE FROM rooms",
    "DELETE FROM sites",
]


def db_url_for(database: str = TEST_DB, user: str | None = None, password: str | None = None) -> str:
    url = make_url(ADMIN_URL).set(database=database)
    if user is not None:
        url = url.set(username=user, password=password)
    return url.render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logging"] = False
    return cfg


async def run_alembic(url: str, action: str, revision: str) -> None:
    cfg = alembic_config(url)
    fn = command.upgrade if action == "upgrade" else command.downgrade
    # env.py calls asyncio.run(); run it on a worker thread with its own loop.
    await asyncio.to_thread(fn, cfg, revision)


async def _ensure_roles(admin: AsyncEngine) -> None:
    async with admin.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for role in ("gcc_app", "gcc_ingest", "gcc_superset_ro"):
            exists = (
                await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
            ).first()
            if not exists:
                await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{TEST_ROLE_PASSWORD}'"))


@pytest.fixture(scope="session")
async def database_url() -> AsyncIterator[str]:
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    await _ensure_roles(admin)
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    url = db_url_for()
    await run_alembic(url, "upgrade", "head")
    yield url
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    await admin.dispose()


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    from app.core import db

    eng = create_async_engine(database_url, pool_size=5, max_overflow=5)
    db.set_engine(eng)
    yield eng
    await eng.dispose()


async def truncate_data(engine: AsyncEngine) -> None:
    """Delete test data in FK order, keeping the reference data written by migrations."""
    async with engine.begin() as conn:
        for stmt in _CLEANUP:
            await conn.execute(text(stmt))


@pytest.fixture
async def clean_db(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    await truncate_data(engine)
    yield engine


@pytest.fixture
async def session(clean_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(clean_db, expire_on_commit=False)() as s:
        yield s
