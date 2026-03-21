"""PostgreSQL integration test fixtures.

Connects to a real PostgreSQL database (configured via PG_TEST_URL env var,
defaults to localhost:5433 / docker-compose.test.yml settings).
Runs all migrations in order before each test session.

Usage:
    docker compose -f docker-compose.test.yml up -d
    python -m pytest tests/postgres/ -v
    # or override DB:
    PG_TEST_URL=postgresql://user:pass@host:5432/db python -m pytest tests/postgres/ -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Database URL — uses a dedicated test DB to isolate from dev
# ---------------------------------------------------------------------------
_DEFAULT_PG_URL = "postgresql+asyncpg://agr_test:agr_test_password@localhost:5433/agr_test"
PG_TEST_URL = os.environ.get("PG_TEST_URL", _DEFAULT_PG_URL)

pg_engine = create_async_engine(PG_TEST_URL, echo=False, pool_pre_ping=True)
pg_session_factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Migration paths — relative to repo root
# ---------------------------------------------------------------------------
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATIONS_DIR = _REPO_ROOT / "infra" / "migrations"

_MIGRATION_FILES = [
    "001_initial_schema.sql",
    "002_approval_enhancements.sql",
    "003_default_policy_trigger.sql",
    "004_agents_table.sql",
    "005_webhooks_table.sql",
    "006_audit_partitioning.sql",
    "007_pg_cron_audit_partitions.sql",  # gracefully skips if pg_cron unavailable
    "008_webhook_deliveries.sql",
    "009_agent_active.sql",
    "010_eval_week.sql",
    "011_indexes.sql",
    "012_token_version.sql",
    "013_status_check.sql",
    "014_audit_sequence_per_org.sql",
    "015_audit_agent_index.sql",
]


async def _drop_all(conn: AsyncConnection) -> None:
    """Drop all tables and types — clean slate for each test run."""
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))
    await conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))


async def _run_migrations(conn: AsyncConnection) -> None:
    """Run all migration files in order."""
    for filename in _MIGRATION_FILES:
        path = _MIGRATIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Migration file not found: {path}")
        sql = path.read_text()
        # Use exec_driver_sql so multi-statement DDL files are sent as-is to
        # asyncpg without SQLAlchemy trying to parse/prepare each statement.
        await conn.exec_driver_sql(sql)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def apply_migrations() -> AsyncGenerator[None, None]:
    """Run migrations once per test session.

    Drops and recreates the public schema for a clean slate.
    Skipped entirely if PostgreSQL is unavailable (CI without postgres service).
    """
    try:
        async with pg_engine.begin() as conn:
            await _drop_all(conn)
            await _run_migrations(conn)
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")
        return
    yield


@pytest_asyncio.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a real PostgreSQL session with auto-rollback after each test."""
    async with pg_session_factory() as session:
        try:
            yield session
            await session.rollback()  # always rollback — keep tests isolated
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def pg_org(pg_session: AsyncSession) -> dict[str, str]:
    """Create a test organisation directly in PostgreSQL and return its data."""
    org_id = str(uuid.uuid4())
    api_key = "agr_sk_pgtest" + "x" * 32
    await pg_session.execute(
        text("""
            INSERT INTO organizations (id, name, slug, plan, api_key, eval_count, eval_limit)
            VALUES (:id, :name, :slug, 'developer', :api_key, 0, 1000)
        """),
        {"id": org_id, "name": "PG Test Org", "slug": f"pg-test-{org_id[:8]}", "api_key": api_key},
    )
    await pg_session.flush()
    return {"id": org_id, "api_key": api_key}


@pytest_asyncio.fixture
async def pg_org_b(pg_session: AsyncSession) -> dict[str, str]:
    """Second test organisation for cross-tenant isolation tests."""
    org_id = str(uuid.uuid4())
    api_key = "agr_sk_pgtestb" + "y" * 31
    await pg_session.execute(
        text("""
            INSERT INTO organizations (id, name, slug, plan, api_key, eval_count, eval_limit)
            VALUES (:id, :name, :slug, 'developer', :api_key, 0, 1000)
        """),
        {
            "id": org_id,
            "name": "PG Test Org B",
            "slug": f"pg-test-b-{org_id[:8]}",
            "api_key": api_key,
        },
    )
    await pg_session.flush()
    return {"id": org_id, "api_key": api_key}


import pytest  # noqa: E402 (must be after fixtures that reference it)
