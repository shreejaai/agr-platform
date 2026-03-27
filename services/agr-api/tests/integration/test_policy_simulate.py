"""Integration tests for POST /v1/policies/simulate."""

import pytest
from app.models import AuditEvent, Organization
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_simulate_allow(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Returns ALLOW for a permitted action with matching policy."""
    response = await client.post(
        "/v1/policies/simulate",
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
    assert data["reason"]
    assert data["decision_trace"]["cedar_decision"] == "ALLOW"
    assert data["decision_trace"]["policy_source"] in ("python_fallback", "cedar_cli")
    assert data["decision_trace"]["matched_policy_id"] is not None


@pytest.mark.asyncio
async def test_simulate_deny(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Returns DENY for a forbidden action."""
    response = await client.post(
        "/v1/policies/simulate",
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
    assert data["decision_trace"]["cedar_decision"] == "DENY"
    assert data["decision_trace"]["risk_override"] is False


@pytest.mark.asyncio
async def test_simulate_approval_required(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Returns APPROVAL_REQUIRED for actions gated by approval policy."""
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "prod-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "APPROVAL_REQUIRED"
    assert data["decision_trace"]["cedar_decision"] == "APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_simulate_decision_trace_populated(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """decision_trace is always present with required fields."""
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    trace = response.json()["decision_trace"]
    assert "policy_source" in trace
    assert "cedar_decision" in trace
    assert "risk_override" in trace
    assert isinstance(trace["risk_override"], bool)


@pytest.mark.asyncio
async def test_simulate_risk_score_included(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """risk_score, risk_level, risk_factors are returned when risk scoring is enabled."""
    response = await client.post(
        "/v1/policies/simulate",
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
    # risk scoring is enabled by default in settings
    assert data["risk_score"] is not None
    assert data["risk_level"] in ("low", "medium", "high")
    assert isinstance(data["risk_factors"], dict)


@pytest.mark.asyncio
async def test_simulate_no_audit_event_written(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Simulate must not write any audit events."""
    before = (await db_session.execute(select(AuditEvent))).scalars().all()

    await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    after = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert len(after) == len(before), "simulate must not write audit events"


@pytest.mark.asyncio
async def test_simulate_risk_override_reflected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """risk_override=True when risk scoring changes Cedar ALLOW to APPROVAL_REQUIRED/DENY."""
    # A high-risk action on a production resource should trigger risk override
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "drop",
            "resource": "prod-db",
            "context": {"environment": "production", "force": "true"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    trace = data["decision_trace"]
    # If risk caused an upgrade, risk_override must be True
    if trace["cedar_decision"] != data["decision"]:
        assert trace["risk_override"] is True
    else:
        assert trace["risk_override"] is False


@pytest.mark.asyncio
async def test_simulate_requires_auth(client: AsyncClient) -> None:
    """Returns 401 without Authorization header."""
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {},
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_simulate_invalid_request_missing_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Returns 422 when required fields are missing."""
    response = await client.post(
        "/v1/policies/simulate",
        json={"agent_id": "coder-001"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_simulate_no_policies_returns_deny(
    client: AsyncClient,
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """When org has no active policies, simulate returns DENY."""
    from app.models import Policy
    from sqlalchemy import update

    await db_session.execute(
        update(Policy).where(Policy.org_id == test_org.id).values(active=False, state="archived")
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {test_org.api_key}"}
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {},
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "DENY"
    assert response.json()["decision_trace"]["policy_source"] == "no_policies"


@pytest.mark.asyncio
async def test_simulate_returns_enriched_compliance_findings(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/policies/simulate",
        json={
            "agent_id": "bot",
            "action": "*",
            "resource": "*",
            "context": {},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    findings = response.json()["compliance_findings"]
    assert findings is not None

    art13 = next(finding for finding in findings if finding["rule_id"] == "ART-13")
    assert art13["passed"] is False
    assert art13["severity_level"] == "medium"
    assert 0 <= art13["compliance_score"] < 100
    assert art13["remediation_steps"][0] == (
        "Use a stable, descriptive `agent_id` instead of a generic identifier."
    )
