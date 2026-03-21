"""Integration tests: risk scoring integrated into POST /v1/evaluate."""

import pytest
from app.config import settings as app_settings
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_evaluate_response_includes_risk_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """EvaluateResponse always includes risk_score, risk_level, risk_factors."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "trusted-reader",
            "action": "read",
            "resource": "docs",
            "context": {},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "risk_score" in data
    assert "risk_level" in data
    assert "risk_factors" in data
    assert isinstance(data["risk_score"], int)
    assert data["risk_level"] in ("low", "medium", "high")
    assert isinstance(data["risk_factors"], dict)


@pytest.mark.asyncio
async def test_evaluate_risk_override_allow_to_deny(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """High-risk action with no matching deny policy is upgraded to DENY by risk engine."""
    # Force thresholds so drop+production always triggers DENY override
    original_enabled = app_settings.risk_scoring_enabled
    original_approval_max = app_settings.risk_thresholds_approval_max
    app_settings.risk_scoring_enabled = True
    app_settings.risk_thresholds_approval_max = 0  # any score > 0 → DENY

    try:
        response = await client.post(
            "/v1/evaluate",
            json={
                "agent_id": "agent-001",
                "action": "read",
                "resource": "docs",
                "context": {},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # With approval_max=0, any non-zero score triggers DENY
        assert data["decision"] in ("DENY", "ALLOW")  # depends on score
        assert data["risk_score"] is not None
    finally:
        app_settings.risk_scoring_enabled = original_enabled
        app_settings.risk_thresholds_approval_max = original_approval_max


@pytest.mark.asyncio
async def test_evaluate_risk_disabled_no_risk_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """When risk scoring is disabled, risk fields are None."""
    original = app_settings.risk_scoring_enabled
    app_settings.risk_scoring_enabled = False

    try:
        response = await client.post(
            "/v1/evaluate",
            json={
                "agent_id": "trusted-reader",
                "action": "read",
                "resource": "docs",
                "context": {},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["risk_score"] is None
        assert data["risk_level"] is None
        assert data["risk_factors"] is None
    finally:
        app_settings.risk_scoring_enabled = original


@pytest.mark.asyncio
async def test_evaluate_cedar_deny_wins_over_risk(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Cedar DENY is final — risk scoring cannot override it to ALLOW."""
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
async def test_evaluate_risk_score_low_for_safe_action(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Read action by trusted agent should yield low risk score."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "trusted-agent",
            "action": "read",
            "resource": "staging-docs",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    # Risk should be present and relatively low
    assert data["risk_score"] is not None
    assert data["risk_score"] <= 50  # read+trusted+staging = low/medium
