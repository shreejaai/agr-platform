"""CRUD for Cedar policies."""

import logging
import uuid
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Policy, PolicyVersion
from app.schemas import (
    ComplianceFindingResponse,
    DecisionTrace,
    PolicyCreate,
    PolicyImportRequest,
    PolicyImportResponse,
    PolicyResponse,
    PolicyUpdate,
    PolicyVersionResponse,
    SimulateRequest,
    SimulateResponse,
)
from app.services.cedar_service import evaluate_request
from app.services.compliance_service import ComplianceContext, ComplianceFinding, get_registry
from app.services.policy_conflict_service import detect_conflicts
from app.services.policy_import_service import export_policies, import_policies
from app.services.redis_service import invalidate_org_eval_cache
from app.services.risk_service import RiskResult, compute_risk_score

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["policies"])

_VALID_STATES = frozenset({"draft", "active", "archived"})


def _state_to_active(state: str) -> bool:
    """Only 'active' policies participate in evaluation."""
    return state == "active"


def _serialize_compliance_findings(
    findings: list[ComplianceFinding],
) -> list[ComplianceFindingResponse]:
    return [
        ComplianceFindingResponse(
            plugin=finding.plugin,
            standard=finding.standard,
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.message,
            passed=finding.passed,
            remediation_steps=finding.remediation_steps,
            severity_level=cast(
                Literal["low", "medium", "high", "critical"], finding.severity_level
            ),
            compliance_score=finding.compliance_score,
        )
        for finding in findings
    ]


async def _snapshot_policy(session: AsyncSession, policy: Policy) -> None:
    """Write the current policy state to policy_versions before a mutation."""
    snapshot = PolicyVersion(
        id=uuid.uuid4(),
        policy_id=policy.id,
        org_id=policy.org_id,
        cedar_rule=policy.cedar_rule,
        name=policy.name,
        level=policy.level,
        state=policy.state,
        version=policy.version,
    )
    session.add(snapshot)


def _version_to_response(v: PolicyVersion) -> PolicyVersionResponse:
    return PolicyVersionResponse(
        id=str(v.id),
        policy_id=str(v.policy_id),
        org_id=str(v.org_id),
        cedar_rule=v.cedar_rule,
        name=v.name,
        level=v.level,
        state=v.state,
        version=v.version,
        created_at=v.created_at,
    )


def _policy_to_response(p: Policy, conflicts: list[str] | None = None) -> PolicyResponse:
    return PolicyResponse(
        id=str(p.id),
        org_id=str(p.org_id),
        project_id=str(p.project_id) if p.project_id else None,
        agent_id=p.agent_id,
        name=p.name,
        level=p.level,
        cedar_rule=p.cedar_rule,
        version=p.version,
        active=p.active,
        state=p.state,
        created_at=p.created_at,
        updated_at=p.updated_at,
        conflicts=conflicts,
    )


async def _check_conflicts(
    session: AsyncSession,
    org_id: uuid.UUID,
    cedar_rule: str,
    name: str,
    exclude_policy_id: uuid.UUID | None = None,
) -> list[str]:
    """Load active+draft policies and run conflict detection."""
    stmt = select(Policy).where(
        Policy.org_id == org_id,
        Policy.state.in_(["active", "draft"]),
    )
    if exclude_policy_id is not None:
        stmt = stmt.where(Policy.id != exclude_policy_id)
    result = await session.execute(stmt)
    existing = [
        {"id": str(p.id), "name": p.name, "cedar_rule": p.cedar_rule}
        for p in result.scalars().all()
    ]
    return detect_conflicts(cedar_rule, name, existing)


@router.get("/policies", response_model=list[PolicyResponse])
async def list_policies(
    request: Request,
    session: AsyncSession = Depends(get_session),
    active: bool | None = None,
    state: str | None = Query(default=None, pattern=r"^(draft|active|archived)$"),
) -> list[PolicyResponse]:
    org_id: uuid.UUID = request.state.org_id
    stmt = select(Policy).where(Policy.org_id == org_id)
    if state is not None:
        stmt = stmt.where(Policy.state == state)
    elif active is not None:
        # backward-compat: active=True → state=active, active=False → non-active
        stmt = stmt.where(Policy.active == active)
    stmt = stmt.order_by(Policy.created_at.desc())
    result = await session.execute(stmt)
    policies = result.scalars().all()
    return [_policy_to_response(p) for p in policies]


@router.post("/policies", response_model=PolicyResponse, status_code=201)
async def create_policy(
    body: PolicyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    conflicts = await _check_conflicts(session, org_id, body.cedar_rule, body.name)
    is_active = _state_to_active(body.state)
    policy = Policy(
        id=uuid.uuid4(),
        org_id=org_id,
        project_id=body.project_id,
        agent_id=body.agent_id,
        name=body.name,
        level=body.level,
        cedar_rule=body.cedar_rule,
        state=body.state,
        active=is_active,
    )
    session.add(policy)
    await session.flush()
    await session.refresh(policy)
    if is_active:
        await invalidate_org_eval_cache(org_id)
    return _policy_to_response(policy, conflicts=conflicts or None)


# NOTE: /policies/import, /policies/export, /policies/simulate MUST be before
# /{policy_id} so FastAPI does not attempt to parse those literals as UUIDs.


@router.post("/policies/import", response_model=PolicyImportResponse, status_code=200)
async def bulk_import_policies(
    body: PolicyImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyImportResponse:
    """Bulk import policies from a JSON list.

    Set dry_run=true to validate without writing.
    Set overwrite=true to update existing policies with matching names.
    """
    org_id: uuid.UUID = request.state.org_id
    result = await import_policies(session, org_id, body)
    if not body.dry_run:
        await invalidate_org_eval_cache(org_id)
    return result


@router.get("/policies/export")
async def bulk_export_policies(
    request: Request,
    session: AsyncSession = Depends(get_session),
    active_only: bool = Query(False, description="Export only active policies"),
) -> JSONResponse:
    """Export all org policies as a JSON array suitable for re-import."""
    org_id: uuid.UUID = request.state.org_id
    policies = await export_policies(session, org_id, active_only=active_only)
    return JSONResponse(
        content={"policies": policies, "total": len(policies)},
        headers={"Content-Disposition": "attachment; filename=policies_export.json"},
    )


@router.post("/policies/simulate", response_model=SimulateResponse)
async def simulate_policy(
    body: SimulateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SimulateResponse:
    """Simulate a policy decision without any side effects.

    Runs the full Cedar evaluation + risk scoring pipeline against the org's
    active policies but writes nothing — no audit event, no approval row,
    no cache entry, no eval_count increment.
    """
    org_id: uuid.UUID = request.state.org_id

    result = await evaluate_request(
        session=session,
        org_id=org_id,
        agent_id=body.agent_id,
        action=body.action,
        resource=body.resource,
        context=body.context,
    )

    cedar_decision = result.decision

    risk: RiskResult | None = None
    if settings.risk_scoring_enabled:
        risk = compute_risk_score(
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            context=body.context,
        )
        if result.decision == "ALLOW":
            if risk.score > settings.risk_thresholds_approval_max:
                result.decision = "DENY"
                result.reason = (
                    f"Risk score {risk.score}/100 ({risk.level}) exceeds threshold "
                    f"{settings.risk_thresholds_approval_max}. Action denied."
                )
            elif risk.score > settings.risk_thresholds_allow_max:
                result.decision = "APPROVAL_REQUIRED"
                result.reason = (
                    f"Risk score {risk.score}/100 ({risk.level}) requires human approval. "
                    f"Threshold is {settings.risk_thresholds_allow_max}."
                )

    compliance_findings: list[ComplianceFindingResponse] | None = None
    try:
        comp_result = await get_registry().run_all(
            ComplianceContext(
                org_id=str(org_id),
                agent_id=body.agent_id,
                action=body.action,
                resource=body.resource,
                context=body.context,
                decision=result.decision,
                risk_score=risk.score if risk else None,
                risk_level=risk.level if risk else None,
                risk_factors=risk.factors if risk else None,
            )
        )
        compliance_findings = (
            _serialize_compliance_findings(comp_result.findings) if comp_result.findings else None
        )
    except Exception as exc:
        logger.warning("Compliance hooks failed during simulate (ignoring): %s", exc)

    return SimulateResponse(
        decision=result.decision,
        reason=result.reason,
        policy_id=result.policy_id,
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        risk_factors=risk.factors if risk else None,
        compliance_findings=compliance_findings,
        decision_trace=DecisionTrace(
            policy_source=result.policy_source,
            matched_policy_id=result.policy_id,
            cedar_decision=cedar_decision,
            risk_score=risk.score if risk else None,
            risk_level=risk.level if risk else None,
            risk_override=risk is not None and result.decision != cedar_decision,
        ),
    )


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(
            Policy.id == policy_id,
            Policy.org_id == org_id,
            Policy.state != "archived",
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(
            Policy.id == policy_id,
            Policy.org_id == org_id,
            Policy.state != "archived",
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    changed = (
        (body.cedar_rule is not None and body.cedar_rule != policy.cedar_rule)
        or (body.name is not None and body.name != policy.name)
        or (body.active is not None)
    )
    if changed:
        await _snapshot_policy(session, policy)

    new_rule = body.cedar_rule if body.cedar_rule is not None else policy.cedar_rule
    new_name = body.name if body.name is not None else policy.name
    conflicts: list[str] | None = None
    if body.cedar_rule is not None and body.cedar_rule != policy.cedar_rule:
        conflicts = (
            await _check_conflicts(session, org_id, new_rule, new_name, exclude_policy_id=policy_id)
            or None
        )
        policy.cedar_rule = body.cedar_rule
        policy.version += 1
    if body.name is not None:
        policy.name = body.name
    # backward-compat: patching active=True/False maps to state transitions
    if body.active is not None:
        if body.active:
            policy.state = "active"
            policy.active = True
        else:
            policy.state = "archived"
            policy.active = False

    await session.flush()
    await session.refresh(policy)
    await invalidate_org_eval_cache(org_id)
    return _policy_to_response(policy, conflicts=conflicts)


@router.patch("/policies/{policy_id}/activate", response_model=PolicyResponse)
async def activate_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    """Transition a draft or archived policy to active state.

    Only active policies are evaluated by the Cedar engine.
    """
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if policy.state == "active":
        return _policy_to_response(policy)

    policy.state = "active"
    policy.active = True
    await session.flush()
    await session.refresh(policy)
    await invalidate_org_eval_cache(org_id)
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}/archive", response_model=PolicyResponse)
async def archive_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    """Archive a policy, removing it from evaluation without hard-deleting it.

    Archived policies preserve the audit trail FK integrity and can be
    inspected but not evaluated or updated.
    """
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if policy.state == "archived":
        return _policy_to_response(policy)

    policy.state = "archived"
    policy.active = False
    await session.flush()
    await session.refresh(policy)
    await invalidate_org_eval_cache(org_id)
    return _policy_to_response(policy)


@router.get(
    "/policies/{policy_id}/versions",
    response_model=list[PolicyVersionResponse],
)
async def list_policy_versions(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[PolicyVersionResponse]:
    """Return the full version history for a policy, newest first.

    Each entry is a snapshot taken immediately before a content-changing PATCH.
    The live policy state is not included — fetch GET /v1/policies/{id} for that.
    """
    org_id: uuid.UUID = request.state.org_id
    # Confirm the policy belongs to this org (any state, including archived)
    exists = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Policy not found.")

    result = await session.execute(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy_id, PolicyVersion.org_id == org_id)
        .order_by(PolicyVersion.version.desc())
    )
    return [_version_to_response(v) for v in result.scalars().all()]


@router.post(
    "/policies/{policy_id}/rollback/{version}",
    response_model=PolicyResponse,
)
async def rollback_policy(
    policy_id: uuid.UUID,
    version: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    """Restore a policy to a previous version snapshot.

    The current state is snapshotted before the restore so the rollback itself
    is reversible. The policy version counter is incremented to indicate a new
    change event.
    """
    org_id: uuid.UUID = request.state.org_id
    policy_result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = policy_result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    snapshot_result = await session.execute(
        select(PolicyVersion).where(
            PolicyVersion.policy_id == policy_id,
            PolicyVersion.org_id == org_id,
            PolicyVersion.version == version,
        )
    )
    snapshot = snapshot_result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"No version {version} found for this policy.",
        )

    # Snapshot current state before overwriting so rollback is reversible
    await _snapshot_policy(session, policy)

    # Restore content from snapshot; advance version counter
    policy.cedar_rule = snapshot.cedar_rule
    policy.name = snapshot.name
    policy.level = snapshot.level
    policy.state = snapshot.state
    policy.active = _state_to_active(snapshot.state)
    policy.version += 1

    await session.flush()
    await session.refresh(policy)
    await invalidate_org_eval_cache(org_id)
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete a policy by archiving it (state=archived, active=False).

    M3: audit_events.policy_id holds historical references to policies;
    hard-deleting would leave stale foreign keys in the immutable audit trail.
    Archiving preserves the row (and audit integrity) while stopping the
    policy from being evaluated in future requests.
    """
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    policy.state = "archived"
    policy.active = False
    await session.flush()
    await invalidate_org_eval_cache(org_id)
