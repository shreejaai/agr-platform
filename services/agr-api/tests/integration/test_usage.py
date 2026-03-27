"""Integration tests for usage tracking and soft quota reporting."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.models import EvaluationUsage, Organization
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_usage_endpoint_returns_per_agent_totals(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    for payload in (
        {
            "agent_id": "alpha-agent",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        {
            "agent_id": "alpha-agent",
            "action": "deploy",
            "resource": "staging-server-2",
            "context": {"environment": "staging"},
        },
        {
            "agent_id": "beta-agent",
            "action": "deploy",
            "resource": "staging-server-3",
            "context": {"environment": "staging"},
        },
    ):
        response = await client.post("/v1/evaluate", json=payload, headers=auth_headers)
        assert response.status_code == 200

    usage_response = await client.get("/v1/usage", headers=auth_headers)
    assert usage_response.status_code == 200
    data = usage_response.json()

    assert data["total_evaluations"] == 3
    assert data["quota_state"] == "ok"
    assert data["per_agent"][0]["agent_id"] == "alpha-agent"
    assert data["per_agent"][0]["total_evaluations"] == 2
    assert data["per_agent"][1]["agent_id"] == "beta-agent"
    assert data["per_agent"][1]["total_evaluations"] == 1


@pytest.mark.asyncio
async def test_usage_endpoint_reports_soft_limit_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        update(Organization)
        .where(Organization.id == test_org.id)
        .values(
            eval_count=1,
            eval_limit=2,
            eval_soft_limit_enabled=True,
            eval_warning_threshold_pct=50,
            eval_week_start=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "warning-agent",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["X-AGR-Usage-State"] in {"warning", "exceeded"}

    usage_response = await client.get("/v1/usage", headers=auth_headers)
    assert usage_response.status_code == 200
    data = usage_response.json()
    assert data["quota_state"] in {"warning", "exceeded"}
    assert data["warning_message"] is not None


@pytest.mark.asyncio
async def test_usage_endpoint_prefers_persisted_agent_totals_when_live_counter_lags(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EvaluationUsage(
                org_id=test_org.id,
                agent_id="alpha-agent",
                total_evaluations=2,
                last_evaluated_at=now,
            ),
            EvaluationUsage(
                org_id=test_org.id,
                agent_id="beta-agent",
                total_evaluations=1,
                last_evaluated_at=now,
            ),
        ]
    )
    await db_session.commit()

    async def _fake_live_total(org_id: uuid.UUID, db_count: int) -> int:
        assert org_id == test_org.id
        assert db_count == 0
        return 2

    monkeypatch.setattr("app.routes.usage.get_current_eval_count", _fake_live_total)

    usage_response = await client.get("/v1/usage", headers=auth_headers)
    assert usage_response.status_code == 200
    data = usage_response.json()

    assert data["total_evaluations"] == 3
    assert data["per_agent"][0]["share_pct"] == 67
    assert data["per_agent"][1]["share_pct"] == 33
