"""Compliance posture summary and export endpoints."""

import csv
import io
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AuditEvent, Organization
from app.schemas import ComplianceSummaryResponse
from app.services.compliance_service import normalize_compliance_finding_payload

router = APIRouter(prefix="/v1", tags=["compliance"])


def _require_admin(request: Request) -> None:
    """Raise 403 if the caller's org role is not admin."""
    role: str = getattr(request.state, "role", "viewer")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for this operation.")


_SAMPLE_LIMIT = 1000  # max recent events to sample for compliance analysis


def _payload_risk_score(payload: dict[str, object]) -> int | None:
    value = payload.get("risk_score")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _payload_risk_level(payload: dict[str, object]) -> str | None:
    value = payload.get("risk_level")
    return value if isinstance(value, str) else None


def _payload_risk_factors(payload: dict[str, object]) -> dict[str, int] | None:
    raw = payload.get("risk_factors")
    if not isinstance(raw, dict):
        return None

    normalized: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool):
            normalized[key] = value
    return normalized or None


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
    finding_scores: list[int] = []

    for event in events:
        payload = event.payload or {}
        risk_score = _payload_risk_score(payload)
        risk_level = _payload_risk_level(payload)
        risk_factors = _payload_risk_factors(payload)

        # High-risk detection
        if risk_level in ("high", "critical"):
            high_risk_count += 1

        # Compliance findings embedded in payload
        raw_findings = payload.get("compliance_findings") or []
        for finding in raw_findings if isinstance(raw_findings, list) else []:
            if not isinstance(finding, dict):
                continue
            normalized = normalize_compliance_finding_payload(
                finding,
                risk_score=risk_score,
                risk_level=risk_level,
                risk_factors=risk_factors,
            )
            standard = str(normalized.get("standard", "UNKNOWN"))
            if normalized.get("passed"):
                findings_by_standard[standard]["pass"] += 1
            else:
                findings_by_standard[standard]["fail"] += 1
            score = normalized.get("compliance_score")
            if isinstance(score, int):
                finding_scores.append(score)

    overall_pass = all(v["fail"] == 0 for v in findings_by_standard.values())
    compliance_score = round(sum(finding_scores) / len(finding_scores)) if finding_scores else 100

    return ComplianceSummaryResponse(
        period_days=period_days,
        total_evaluations=total,
        decisions=decisions,
        high_risk_count=high_risk_count,
        findings_by_standard=dict(findings_by_standard),
        overall_pass=overall_pass,
        compliance_score=compliance_score,
    )


@router.get(
    "/compliance/export",
    summary="Export compliance report",
    description=(
        "Export a compliance posture report for the requested period. "
        "**Admin role required.** "
        "Supported formats: `json` (default), `csv`, and `pdf` (falls back to JSON when PDF rendering is unavailable). "
        "The JSON export includes org info, risk summary, audit trail summary, "
        "policy violations, per-standard pass/fail counts, and a row per compliance finding."
    ),
)
async def export_compliance(
    request: Request,
    session: AsyncSession = Depends(get_session),
    period_days: int = Query(default=7, ge=1, le=90),
    format: str = Query(default="json", pattern=r"^(json|csv|pdf)$"),  # noqa: A002
) -> Response:
    """Download a compliance report in JSON or CSV format. Admin-only."""
    _require_admin(request)

    org: Organization = request.state.org
    org_id: uuid.UUID = request.state.org_id
    since = datetime.now(UTC) - timedelta(days=period_days)
    generated_at = datetime.now(UTC).isoformat()

    # Decision counts
    decision_rows = await session.execute(
        select(AuditEvent.decision, func.count().label("cnt"))
        .where(AuditEvent.org_id == org_id, AuditEvent.recorded_at >= since)
        .group_by(AuditEvent.decision)
    )
    decisions: dict[str, int] = {row[0]: row[1] for row in decision_rows.all()}
    total = sum(decisions.values())

    # Audit trail summary — first/last event timestamps
    audit_bounds = await session.execute(
        select(func.min(AuditEvent.recorded_at), func.max(AuditEvent.recorded_at)).where(
            AuditEvent.org_id == org_id, AuditEvent.recorded_at >= since
        )
    )
    bounds_row = audit_bounds.one()
    audit_first = bounds_row[0].isoformat() if bounds_row[0] else None
    audit_last = bounds_row[1].isoformat() if bounds_row[1] else None

    # Sample recent events for findings + risk summary
    events_result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id, AuditEvent.recorded_at >= since)
        .order_by(AuditEvent.recorded_at.desc())
        .limit(_SAMPLE_LIMIT)
    )
    events = events_result.scalars().all()

    high_risk_count = 0
    findings: list[dict[str, object]] = []
    findings_by_standard: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    finding_scores: list[int] = []
    risk_scores: list[int] = []
    risk_by_level: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    policy_violations: list[dict[str, object]] = []
    remediation_counts: dict[str, int] = defaultdict(int)
    event_types_by_count: dict[str, int] = defaultdict(int)

    for event in events:
        payload = event.payload or {}
        risk_score = _payload_risk_score(payload)
        risk_level = _payload_risk_level(payload)
        risk_factors = _payload_risk_factors(payload)
        event_types_by_count[event.event_type] += 1

        if risk_score is not None:
            risk_scores.append(risk_score)
        if risk_level in risk_by_level:
            risk_by_level[risk_level] += 1
        if risk_level in ("high", "critical"):
            high_risk_count += 1

        if event.decision == "DENY":
            policy_violations.append(
                {
                    "event_id": str(event.id),
                    "recorded_at": event.recorded_at.isoformat() if event.recorded_at else "",
                    "agent_id": event.agent_id,
                    "action": event.action,
                    "resource": event.resource,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                }
            )

        raw = payload.get("compliance_findings") or []
        for finding in raw if isinstance(raw, list) else []:
            if not isinstance(finding, dict):
                continue
            normalized = normalize_compliance_finding_payload(
                finding,
                risk_score=risk_score,
                risk_level=risk_level,
                risk_factors=risk_factors,
            )
            standard = str(normalized.get("standard", "UNKNOWN"))
            passed = bool(normalized.get("passed"))
            if passed:
                findings_by_standard[standard]["pass"] += 1
            else:
                findings_by_standard[standard]["fail"] += 1
            score = normalized.get("compliance_score")
            if isinstance(score, int):
                finding_scores.append(score)
            findings.append(
                {
                    "event_id": str(event.id),
                    "recorded_at": event.recorded_at.isoformat() if event.recorded_at else "",
                    "agent_id": event.agent_id,
                    "action": event.action,
                    "decision": event.decision,
                    "plugin": str(normalized.get("plugin", "")),
                    "standard": standard,
                    "rule_id": str(normalized.get("rule_id", "UNKNOWN")),
                    "severity": str(normalized.get("severity", "info")),
                    "severity_level": str(normalized.get("severity_level", "low")),
                    "compliance_score": score if isinstance(score, int) else 100,
                    "passed": passed,
                    "message": str(normalized.get("message", "")),
                    "remediation_steps": normalized.get("remediation_steps", []),
                }
            )
            raw_steps = normalized.get("remediation_steps")
            if isinstance(raw_steps, list):
                for step in raw_steps:
                    if isinstance(step, str) and step:
                        remediation_counts[step] += 1

    filename = f"agr-compliance-{datetime.now(UTC).strftime('%Y%m%d')}"
    compliance_score = round(sum(finding_scores) / len(finding_scores)) if finding_scores else 100
    avg_risk_score = round(sum(risk_scores) / len(risk_scores)) if risk_scores else None

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "event_id",
                "recorded_at",
                "agent_id",
                "action",
                "decision",
                "plugin",
                "standard",
                "rule_id",
                "severity",
                "severity_level",
                "compliance_score",
                "passed",
                "message",
                "remediation_steps",
            ]
        )
        for row in findings:
            raw_steps = row.get("remediation_steps")
            remediation_steps = raw_steps if isinstance(raw_steps, list) else []
            writer.writerow(
                [
                    row["event_id"],
                    row["recorded_at"],
                    row["agent_id"],
                    row["action"],
                    row["decision"],
                    row["plugin"],
                    row["standard"],
                    row["rule_id"],
                    row["severity"],
                    row["severity_level"],
                    row["compliance_score"],
                    row["passed"],
                    row["message"],
                    " | ".join(step for step in remediation_steps if isinstance(step, str)),
                ]
            )
        csv_bytes = buf.getvalue().encode()
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    response_format = format
    fallback_headers: dict[str, str] = {}
    if format == "pdf":
        # No PDF rendering dependency is in the current stack; keep the API stable
        # by falling back to the JSON export rather than introducing a heavy renderer.
        response_format = "json"
        fallback_headers["X-AGR-Export-Fallback"] = "json"
        fallback_headers["X-AGR-Export-Fallback-Reason"] = (
            "PDF export is not available in the current deployment stack."
        )

    remediation_steps = [
        {"step": step, "occurrences": count}
        for step, count in sorted(
            remediation_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    # JSON export — enriched with org info, risk summary, audit trail summary
    report = {
        "generated_at": generated_at,
        "format": response_format,
        "org_info": {
            "org_id": str(org_id),
            "name": org.name,
            "plan": org.plan,
            "slug": org.slug,
            "role": getattr(request.state, "role", org.role),
        },
        "period_days": period_days,
        "audit_trail_summary": {
            "total_events": total,
            "first_event": audit_first,
            "last_event": audit_last,
            "sampled_event_types": dict(sorted(event_types_by_count.items())),
        },
        "decisions": decisions,
        "policy_violations": policy_violations,
        "risk_summary": {
            "avg_score": avg_risk_score,
            "high_critical_count": high_risk_count,
            "by_level": risk_by_level,
        },
        "remediation_steps": remediation_steps,
        "findings_by_standard": {k: dict(v) for k, v in findings_by_standard.items()},
        "overall_pass": all(v["fail"] == 0 for v in findings_by_standard.values()),
        "compliance_score": compliance_score,
        "findings": findings,
    }
    return Response(
        content=json.dumps(report, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.json"',
            **fallback_headers,
        },
    )
