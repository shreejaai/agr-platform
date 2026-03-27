"""GET /v1/compliance/summary — aggregate compliance posture view."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AuditEvent
from app.schemas import ComplianceSummaryResponse

router = APIRouter(prefix="/v1", tags=["compliance"])

_SAMPLE_LIMIT = 1000  # max recent events to sample for compliance analysis


@router.get("/compliance/summary", response_model=ComplianceSummaryResponse)
async def compliance_summary(
    request: Request,
    session: AsyncSession = Depends(get_session),
    period_days: int = Query(default=7, ge=1, le=90),
) -> ComplianceSummaryResponse:
    """Return an aggregated compliance posture for the last N days.

    Computes:
    - Total evaluation count and decision breakdown
    - High-risk event count (payload.risk_level == "high")
    - Compliance findings aggregated from stored payload data

    Compliance findings are stored in audit event payloads during /evaluate.
    This endpoint aggregates them across recent events.
    """
    org_id: uuid.UUID = request.state.org_id
    since = datetime.now(UTC) - timedelta(days=period_days)

    # Decision counts
    decision_rows = await session.execute(
        select(AuditEvent.decision, func.count().label("cnt"))
        .where(AuditEvent.org_id == org_id, AuditEvent.recorded_at >= since)
        .group_by(AuditEvent.decision)
    )
    decisions: dict[str, int] = {}
    total = 0
    for row in decision_rows.all():
        decisions[row[0]] = row[1]
        total += row[1]

    # Sample recent events for high-risk count + compliance findings
    events_result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id, AuditEvent.recorded_at >= since)
        .order_by(AuditEvent.recorded_at.desc())
        .limit(_SAMPLE_LIMIT)
    )
    events = events_result.scalars().all()

    high_risk_count = 0
    findings_by_standard: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})

    for event in events:
        payload = event.payload or {}

        # High-risk detection
        if payload.get("risk_level") == "high":
            high_risk_count += 1

        # Compliance findings embedded in payload
        raw_findings = payload.get("compliance_findings") or []
        for finding in raw_findings if isinstance(raw_findings, list) else []:
            standard = str(finding.get("standard", "UNKNOWN"))
            if finding.get("passed"):
                findings_by_standard[standard]["pass"] += 1
            else:
                findings_by_standard[standard]["fail"] += 1

    overall_pass = all(v["fail"] == 0 for v in findings_by_standard.values())

    return ComplianceSummaryResponse(
        period_days=period_days,
        total_evaluations=total,
        decisions=decisions,
        high_risk_count=high_risk_count,
        findings_by_standard=dict(findings_by_standard),
        overall_pass=overall_pass,
    )
