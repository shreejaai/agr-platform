"""Integration tests for multi-tenant isolation."""

import uuid

import pytest
from app.models import Organization
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_org_b_cannot_see_org_a_policies(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """Org B's API key should not see Org A's policies."""
    # Create org B
    org_b = Organization(
        id=uuid.uuid4(),
        name="Org B",
        slug="org-b",
        plan="developer",
        api_key="agr_sk_orgbkey99999999999999999999999999999abcdef0",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org_b)
    await db_session.commit()

    # Org A should see policies
    resp_a = await client.get("/v1/policies", headers=auth_headers)
    assert resp_a.status_code == 200
    assert len(resp_a.json()) >= 3

    # Org B should see no policies
    resp_b = await client.get(
        "/v1/policies",
        headers={"Authorization": f"Bearer {org_b.api_key}"},
    )
    assert resp_b.status_code == 200
    assert len(resp_b.json()) == 0


@pytest.mark.asyncio
async def test_org_b_cannot_see_org_a_audit_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """Org B cannot see Org A's audit events."""
    # Create an eval for Org A
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

    # Create org B
    org_b = Organization(
        id=uuid.uuid4(),
        name="Org B",
        slug="org-b-audit",
        plan="developer",
        api_key="agr_sk_orgbaudit999999999999999999999999999abcdef0",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org_b)
    await db_session.commit()

    # Org A sees audit events
    resp_a = await client.get("/v1/audit", headers=auth_headers)
    assert resp_a.status_code == 200
    assert len(resp_a.json()) >= 1

    # Org B sees none
    resp_b = await client.get(
        "/v1/audit",
        headers={"Authorization": f"Bearer {org_b.api_key}"},
    )
    assert resp_b.status_code == 200
    assert len(resp_b.json()) == 0
