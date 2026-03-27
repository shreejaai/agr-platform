"""Integration tests for compliance summary and export endpoints."""

import json
import uuid

import pytest
from app.models import AuditEvent, Organization
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _downgrade_latest_compliance_payload(
    db_session: AsyncSession, test_org: Organization
) -> None:
    result = await db_session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == test_org.id)
        .order_by(AuditEvent.recorded_at.desc())
    )
    event = result.scalars().first()
    assert event is not None

    payload = dict(event.payload or {})
    raw_findings = payload.get("compliance_findings")
    assert isinstance(raw_findings, list)

    downgraded_findings: list[dict[str, object]] = []
    for finding in raw_findings:
        assert isinstance(finding, dict)
        downgraded_findings.append(
            {
                key: value
                for key, value in finding.items()
                if key not in {"remediation_steps", "severity_level", "compliance_score"}
            }
        )

    payload["compliance_findings"] = downgraded_findings
    event.payload = payload
    await db_session.commit()


@pytest.mark.asyncio
async def test_compliance_summary_backfills_scores_for_older_payloads(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    create_response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "bot",
            "action": "*",
            "resource": "*",
            "context": {},
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 200

    await _downgrade_latest_compliance_payload(db_session, test_org)

    response = await client.get("/v1/compliance/summary?period_days=7", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["overall_pass"] is False
    assert data["compliance_score"] < 100
    assert data["findings_by_standard"]["SOC2"]["fail"] >= 1


@pytest.mark.asyncio
async def test_compliance_export_json_includes_remediation_for_older_payloads(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    create_response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "bot",
            "action": "*",
            "resource": "*",
            "context": {},
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 200

    await _downgrade_latest_compliance_payload(db_session, test_org)

    response = await client.get(
        "/v1/compliance/export?period_days=7&format=json",
        headers=auth_headers,
    )

    assert response.status_code == 200
    report = json.loads(response.text)
    assert report["compliance_score"] < 100
    finding = report["findings"][0]
    assert "remediation_steps" in finding
    assert "severity_level" in finding
    assert "compliance_score" in finding
    assert isinstance(finding["remediation_steps"], list)


@pytest.mark.asyncio
async def test_compliance_export_json_enriched_fields(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
) -> None:
    """JSON export includes org_info, risk_summary, audit_trail_summary, policy_violations."""
    await client.post(
        "/v1/evaluate",
        json={"agent_id": "bot", "action": "*", "resource": "*", "context": {}},
        headers=auth_headers,
    )

    response = await client.get(
        "/v1/compliance/export?period_days=7&format=json",
        headers=auth_headers,
    )

    assert response.status_code == 200
    report = json.loads(response.text)

    # org_info section
    assert "org_info" in report
    assert report["org_info"]["name"] == test_org.name
    assert report["org_info"]["plan"] == test_org.plan

    # audit_trail_summary section
    assert "audit_trail_summary" in report
    assert "total_events" in report["audit_trail_summary"]
    assert report["audit_trail_summary"]["total_events"] >= 1

    # risk_summary section
    assert "risk_summary" in report
    assert "avg_score" in report["risk_summary"]
    assert "by_level" in report["risk_summary"]
    assert "high_critical_count" in report["risk_summary"]

    # policy_violations (may be empty for ALLOW decisions)
    assert "policy_violations" in report
    assert isinstance(report["policy_violations"], list)
    assert "remediation_steps" in report
    assert isinstance(report["remediation_steps"], list)


@pytest.mark.asyncio
async def test_compliance_export_pdf_falls_back_to_json(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await client.post(
        "/v1/evaluate",
        json={"agent_id": "bot", "action": "*", "resource": "*", "context": {}},
        headers=auth_headers,
    )

    response = await client.get(
        "/v1/compliance/export?period_days=7&format=pdf",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["X-AGR-Export-Fallback"] == "json"
    report = json.loads(response.text)
    assert report["format"] == "json"


@pytest.mark.asyncio
async def test_compliance_export_requires_admin(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Non-admin role gets 403 on export endpoint."""
    viewer_org = Organization(
        id=uuid.uuid4(),
        name="Viewer Org",
        slug="viewer-org",
        plan="developer",
        api_key="agr_sk_viewerkey1234567890123456789012345678abcdef",
        eval_count=0,
        eval_limit=1000,
        role="viewer",
    )
    db_session.add(viewer_org)
    await db_session.commit()

    response = await client.get(
        "/v1/compliance/export?format=json",
        headers={"Authorization": f"Bearer {viewer_org.api_key}"},
    )
    assert response.status_code == 403
