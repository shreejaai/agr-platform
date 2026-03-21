"""Integration tests for POST /v1/evaluate — the core endpoint."""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import AuditEvent, Organization, Policy
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_evaluate_allow_staging_deploy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns ALLOW for staging deploy."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW"
    assert data["eval_id"]
    assert data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_evaluate_deny_production_db_drop(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns DENY for production db.drop."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "db.drop",
            "resource": "production-db",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"


@pytest.mark.asyncio
async def test_evaluate_approval_required_production_deploy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns APPROVAL_REQUIRED for production deploy."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "APPROVAL_REQUIRED"
    assert data["approval_id"] is not None
    assert "requires human approval" in data["reason"]


@pytest.mark.asyncio
async def test_evaluate_returns_401_without_auth(client: AsyncClient) -> None:
    """POST /v1/evaluate returns 401 without Authorization header."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_returns_401_with_invalid_key(client: AsyncClient) -> None:
    """POST /v1/evaluate returns 401 with invalid API key."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
        },
        headers={"Authorization": "Bearer agr_sk_invalidkey"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_returns_429_when_limit_exceeded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """POST /v1/evaluate returns 429 when eval_limit is exceeded."""
    await db_session.execute(
        update(Organization)
        .where(Organization.id == test_org.id)
        .values(
            eval_count=10000,
            eval_limit=10000,
            eval_week_start=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 429
    data = response.json()
    assert data["error"] == "eval_limit_exceeded"
    assert "upgrade_url" in data


@pytest.mark.asyncio
async def test_evaluate_writes_audit_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """POST /v1/evaluate creates a valid audit event."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200

    result = await db_session.execute(select(AuditEvent).where(AuditEvent.org_id == test_org.id))
    events = result.scalars().all()
    assert len(events) >= 1
    event = events[0]
    assert event.event_type == "TOOL_ALLOW"
    assert event.agent_id == "coder-001"
    assert event.entry_hash
    assert len(event.entry_hash) == 64


@pytest.mark.asyncio
async def test_evaluate_hash_chain_valid(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """Two consecutive evaluations produce a valid hash chain."""
    await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "a1",
            "action": "deploy",
            "resource": "s1",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "a2",
            "action": "deploy",
            "resource": "s2",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.org_id == test_org.id).order_by(AuditEvent.sequence_num)
    )
    events = result.scalars().all()
    assert len(events) >= 2

    first = events[0]
    second = events[1]
    assert first.prev_hash is None
    assert second.prev_hash == first.entry_hash


@pytest.mark.asyncio
async def test_evaluate_deny_default_no_policies(
    client: AsyncClient,
    db_session: AsyncSession,
    test_org: Organization,
    auth_headers: dict[str, str],
) -> None:
    """Evaluate with no matching policies returns DENY (safe default)."""
    await db_session.execute(select(Policy).where(Policy.org_id == test_org.id))
    # Delete all policies for this org
    from sqlalchemy import delete

    await db_session.execute(delete(Policy).where(Policy.org_id == test_org.id))
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={"agent_id": "a1", "action": "unknown", "resource": "r1"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"
