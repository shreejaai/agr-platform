"""Test fixtures — uses SQLite for integration tests (no PostgreSQL dependency in CI)."""

import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "agr-core"))

from app.database import get_session
from app.models import Agent, Base, Organization, Policy  # noqa: F401

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with test_session_factory() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
        slug="test-org",
        plan="developer",
        api_key="agr_sk_testkey123456789012345678901234567890abcdef",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def test_org_b(db_session: AsyncSession) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org B",
        slug="test-org-b",
        plan="developer",
        api_key="agr_sk_orgbkey12345678901234567890123456789abcdef0",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def test_policies(db_session: AsyncSession, test_org: Organization) -> list[Policy]:
    policies = [
        Policy(
            id=uuid.uuid4(),
            org_id=test_org.id,
            name="Allow staging deploy",
            level="org",
            cedar_rule='permit(principal, action == Action::"deploy", resource)\n'
            'when { resource has environment && resource.environment == "staging" };',
            active=True,
        ),
        Policy(
            id=uuid.uuid4(),
            org_id=test_org.id,
            name="Block production DB drops",
            level="org",
            cedar_rule='forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], '
            "resource)\n"
            'when { resource has environment && resource.environment == "production" };',
            active=True,
        ),
        Policy(
            id=uuid.uuid4(),
            org_id=test_org.id,
            name="Require approval for production deploy",
            level="org",
            cedar_rule='forbid(principal, action == Action::"deploy", resource)\n'
            'when { resource has environment && resource.environment == "production" }\n'
            "unless { context has approval_status && context.approval_status == "
            '"approved" };',
            active=True,
        ),
    ]
    for p in policies:
        db_session.add(p)
    await db_session.commit()
    return policies


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, test_org: Organization, test_policies: list[Policy]
) -> AsyncGenerator[AsyncClient, None]:
    # Patch the auth middleware and session factory for tests
    import app.database as db_mod
    import app.middleware.auth as auth_mod
    from app.main import app

    original_factory = auth_mod.async_session_factory
    auth_mod.async_session_factory = test_session_factory
    db_mod.async_session_factory = test_session_factory

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    auth_mod.async_session_factory = original_factory


@pytest_asyncio.fixture
async def auth_headers(test_org: Organization) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_org.api_key}"}
