"""Integration tests for policy CRUD."""

import pytest
from app.models import Organization, Policy
from app.services.audit_service import create_audit_event
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_list_policies(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/v1/policies", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3


@pytest.mark.asyncio
async def test_create_policy(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/v1/policies",
        json={
            "name": "Custom policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Custom policy"
    assert data["version"] == 1
    # New policies default to draft — not yet active in evaluation
    assert data["state"] == "draft"
    assert data["active"] is False


@pytest.mark.asyncio
async def test_update_policy_increments_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Create as active so it can be found by the update route
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Versioned policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"v1", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    # Update cedar_rule → version should increment
    update_resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2


@pytest.mark.asyncio
async def test_toggle_policy_active(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Toggle policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"test", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"active": False},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["active"] is False
    assert update_resp.json()["state"] == "archived"


@pytest.mark.asyncio
async def test_delete_policy(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Delete me",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"del", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/v1/policies/{policy_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/v1/policies/{policy_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_policy_rejects_invalid_cedar_rule(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/policies",
        json={
            "name": "Invalid policy",
            "level": "org",
            "cedar_rule": "permit(resource);",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "Invalid Cedar rule" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_create_policy_rejects_bad_approval_shape_with_hint(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """W1.2: approval-pattern policy that doesn't compare to "approved" → 400 with hint."""
    response = await client.post(
        "/v1/policies",
        json={
            "name": "Broken approval pattern",
            "level": "org",
            "cedar_rule": (
                'forbid(principal, action == Action::"transfer", resource) '
                'unless { context.approval_status == "ok" };'
            ),
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] is not None
    assert detail["hint"] is not None
    assert "approved" in detail["hint"]
    assert detail["doc_url"] is not None


@pytest.mark.asyncio
async def test_policy_analytics_infers_legacy_audit_rows_without_policy_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
    test_policies: list[Policy],
) -> None:
    allow_staging_policy = next(
        policy for policy in test_policies if policy.name == "Allow staging deploy"
    )

    await create_audit_event(
        session=db_session,
        org_id=test_org.id,
        event_type="TOOL_ALLOW",
        agent_id="coder-001",
        action="deploy",
        resource="staging-server",
        decision="ALLOW",
        payload={"context": {"environment": "staging"}},
    )
    await db_session.commit()

    response = await client.get("/v1/policies/analytics?active=true", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    analytics = next(row for row in data if row["policy_id"] == str(allow_staging_policy.id))
    assert analytics["total_evaluations"] == 1
    assert analytics["decisions"]["ALLOW"] == 1
    assert analytics["last_triggered_at"] is not None
