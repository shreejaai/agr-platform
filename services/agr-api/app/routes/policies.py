"""CRUD for Cedar policies."""

import json
import logging
import time
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.auth import require_scope
from app.models import AuditEvent, Policy, PolicyTestSuite, PolicyVersion
from app.schemas import (
    ComplianceFindingResponse,
    DecisionTrace,
    PolicyAnalyticsResponse,
    PolicyCreate,
    PolicyImportRequest,
    PolicyImportResponse,
    PolicyResponse,
    PolicyTemplateResponse,
    PolicyTestCase,
    PolicyTestCaseResult,
    PolicyTestSuiteCreate,
    PolicyTestSuiteRecordResponse,
    PolicyTestSuiteRequest,
    PolicyTestSuiteResponse,
    PolicyUpdate,
    PolicyVersionResponse,
    SimulateRequest,
    SimulateResponse,
)
from app.services.cedar_service import (
    evaluate_policy_set,
    evaluate_request,
    infer_policy_match,
    validate_cedar_rule,
)
from app.services.compliance_service import ComplianceContext, get_registry
from app.services.policy_conflict_service import detect_conflicts
from app.services.policy_import_service import export_policies, import_policies
from app.services.policy_template_service import load_policy_templates
from app.services.redis_service import invalidate_org_eval_cache
from app.services.risk_service import RiskResult, compute_risk_score

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["policies"])

_VALID_STATES = frozenset({"draft", "active", "archived"})
_POLICY_ANALYTICS_EVENT_TYPES = frozenset({"TOOL_ALLOW", "TOOL_DENY", "APPROVAL_REQUESTED"})


def _state_to_active(state: str) -> bool:
    """Only 'active' policies participate in evaluation."""
    return state == "active"


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


def _suite_to_response(suite: PolicyTestSuite) -> PolicyTestSuiteRecordResponse:
    test_cases = list(suite.test_cases or [])
    return PolicyTestSuiteRecordResponse(
        id=str(suite.id),
        name=suite.name,
        description=suite.description,
        test_cases=[PolicyTestCase.model_validate(test_case) for test_case in test_cases],
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


async def _load_policy_set(
    session: AsyncSession,
    org_id: uuid.UUID,
    agent_id: str,
    policy_ids: list[str] | None,
) -> list[dict[str, str]]:
    if policy_ids is None:
        result = await session.execute(
            select(Policy).where(
                Policy.org_id == org_id,
                Policy.state == "active",
                (Policy.agent_id.is_(None)) | (Policy.agent_id == agent_id),
            )
        )
    else:
        try:
            normalized_ids = [uuid.UUID(policy_id) for policy_id in policy_ids]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid policy id: {exc}") from exc

        result = await session.execute(
            select(Policy).where(
                Policy.org_id == org_id,
                Policy.id.in_(normalized_ids),
            )
        )

    return [{"id": str(policy.id), "cedar_rule": policy.cedar_rule} for policy in result.scalars()]


async def _run_policy_test_suite(
    session: AsyncSession,
    org_id: uuid.UUID,
    body: PolicyTestSuiteRequest,
) -> PolicyTestSuiteResponse:
    started = time.perf_counter()
    results: list[PolicyTestCaseResult] = []

    for test_case in body.test_cases:
        policies = await _load_policy_set(session, org_id, test_case.agent_id, body.policy_ids)
        evaluation = evaluate_policy_set(
            policies,
            test_case.agent_id,
            test_case.action,
            test_case.resource,
            test_case.context,
        )
        passed = evaluation.decision == test_case.expected_decision
        results.append(
            PolicyTestCaseResult(
                name=test_case.name,
                passed=passed,
                actual_decision=evaluation.decision,
                expected_decision=test_case.expected_decision,
                reason=evaluation.reason,
                latency_ms=evaluation.latency_ms,
            )
        )

    passed_count = sum(1 for result in results if result.passed)
    return PolicyTestSuiteResponse(
        total=len(results),
        passed=passed_count,
        failed=len(results) - passed_count,
        results=results,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _to_github_actions_output(result: PolicyTestSuiteResponse) -> str:
    lines: list[str] = []
    for case in result.results:
        if case.passed:
            lines.append(f"::notice title=AGR Policy Test::{case.name} passed")
            continue
        lines.append(
            "::error title=AGR Policy Test::"
            f"{case.name} expected {case.expected_decision} but got {case.actual_decision}. "
            f"{case.reason}"
        )
    if not lines:
        lines.append("::notice title=AGR Policy Test::No test cases were executed")
    return "\n".join(lines)


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


@router.get(
    "/policies",
    response_model=list[PolicyResponse],
    dependencies=[Depends(require_scope("policies:read"))],
)
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


@router.get(
    "/policies/analytics",
    response_model=list[PolicyAnalyticsResponse],
    dependencies=[Depends(require_scope("policies:read"))],
)
async def list_policy_analytics(
    request: Request,
    session: AsyncSession = Depends(get_session),
    active: bool | None = None,
    state: str | None = Query(default=None, pattern=r"^(draft|active|archived)$"),
) -> list[PolicyAnalyticsResponse]:
    """Summarize policy trigger counts from audit history.

    Legacy audit rows may not carry policy_id when the Cedar CLI path was used.
    For those rows, infer the matched policy from the stored request context so
    policy metrics remain visible in the dashboard.
    """
    org_id: uuid.UUID = request.state.org_id

    stmt = select(Policy).where(Policy.org_id == org_id)
    if state is not None:
        stmt = stmt.where(Policy.state == state)
    elif active is not None:
        stmt = stmt.where(Policy.active == active)
    stmt = stmt.order_by(Policy.created_at.desc())
    result = await session.execute(stmt)
    policies = result.scalars().all()
    if not policies:
        return []

    policy_set = [{"id": str(policy.id), "cedar_rule": policy.cedar_rule} for policy in policies]
    analytics_by_policy_id: dict[str, PolicyAnalyticsResponse] = {
        str(policy.id): PolicyAnalyticsResponse(policy_id=str(policy.id)) for policy in policies
    }
    inference_cache: dict[tuple[str, str, str, str], str | None] = {}

    audit_result = await session.execute(
        select(AuditEvent)
        .where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type.in_(tuple(_POLICY_ANALYTICS_EVENT_TYPES)),
        )
        .order_by(AuditEvent.recorded_at.desc())
    )

    for event in audit_result.scalars().all():
        matched_policy_id = str(event.policy_id) if event.policy_id is not None else None
        if matched_policy_id not in analytics_by_policy_id:
            payload = event.payload if isinstance(event.payload, dict) else {}
            raw_context = payload.get("context")
            context = raw_context if isinstance(raw_context, dict) else {}
            cache_key = (
                event.agent_id,
                event.action,
                event.resource,
                json.dumps(context, sort_keys=True, default=str),
            )
            matched_policy_id = inference_cache.get(cache_key)
            if cache_key not in inference_cache:
                inferred = infer_policy_match(
                    policy_set,
                    event.agent_id,
                    event.action,
                    event.resource,
                    context,
                )
                matched_policy_id = inferred.policy_id
                inference_cache[cache_key] = matched_policy_id

        if matched_policy_id is None or matched_policy_id not in analytics_by_policy_id:
            continue

        analytics = analytics_by_policy_id[matched_policy_id]
        analytics.total_evaluations += 1
        if analytics.last_triggered_at is None:
            analytics.last_triggered_at = event.recorded_at
        if event.decision in {"ALLOW", "DENY", "APPROVAL_REQUIRED"}:
            setattr(analytics.decisions, event.decision, getattr(analytics.decisions, event.decision) + 1)

    return list(analytics_by_policy_id.values())


@router.post(
    "/policies",
    response_model=PolicyResponse,
    status_code=201,
    dependencies=[Depends(require_scope("policies:write"))],
)
async def create_policy(
    body: PolicyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    validation = validate_cedar_rule(body.cedar_rule)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=f"Invalid Cedar rule: {validation.error}")
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


@router.post(
    "/policies/import",
    response_model=PolicyImportResponse,
    status_code=200,
    dependencies=[Depends(require_scope("policies:write"))],
)
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


@router.get("/policies/export", dependencies=[Depends(require_scope("policies:read"))])
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


@router.get(
    "/policies/templates",
    response_model=list[PolicyTemplateResponse],
    dependencies=[Depends(require_scope("policies:read"))],
)
async def list_policy_templates() -> list[PolicyTemplateResponse]:
    return [PolicyTemplateResponse.model_validate(item) for item in load_policy_templates()]


@router.post(
    "/policies/simulate",
    response_model=SimulateResponse,
    dependencies=[Depends(require_scope("policies:read"))],
)
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

    compliance_findings: list[dict[str, object]] | None = None
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
        compliance_findings = comp_result.to_dict() if comp_result.findings else None
    except Exception as exc:
        logger.warning("Compliance hooks failed during simulate (ignoring): %s", exc)

    return SimulateResponse(
        decision=result.decision,
        reason=result.reason,
        policy_id=result.policy_id,
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        risk_factors=risk.factors if risk else None,
        compliance_findings=cast(list[ComplianceFindingResponse] | None, compliance_findings),
        decision_trace=DecisionTrace(
            policy_source=result.policy_source,
            matched_policy_id=result.policy_id,
            cedar_decision=cedar_decision,
            risk_score=risk.score if risk else None,
            risk_level=risk.level if risk else None,
            risk_override=risk is not None and result.decision != cedar_decision,
        ),
    )


@router.post(
    "/policies/test",
    response_model=PolicyTestSuiteResponse,
    dependencies=[Depends(require_scope("policies:read"))],
)
async def run_policy_test_cases(
    body: PolicyTestSuiteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyTestSuiteResponse:
    return await _run_policy_test_suite(session, request.state.org_id, body)


@router.get(
    "/policies/test-suites",
    response_model=list[PolicyTestSuiteRecordResponse],
    dependencies=[Depends(require_scope("policies:read"))],
)
async def list_policy_test_suites(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[PolicyTestSuiteRecordResponse]:
    result = await session.execute(
        select(PolicyTestSuite)
        .where(PolicyTestSuite.org_id == request.state.org_id)
        .order_by(PolicyTestSuite.updated_at.desc())
    )
    return [_suite_to_response(suite) for suite in result.scalars().all()]


@router.post(
    "/policies/test-suites",
    response_model=PolicyTestSuiteRecordResponse,
    status_code=201,
    dependencies=[Depends(require_scope("policies:write"))],
)
async def create_policy_test_suite(
    body: PolicyTestSuiteCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyTestSuiteRecordResponse:
    suite = PolicyTestSuite(
        id=uuid.uuid4(),
        org_id=request.state.org_id,
        name=body.name,
        description=body.description,
        test_cases=[test_case.model_dump() for test_case in body.test_cases],
    )
    session.add(suite)
    await session.flush()
    await session.refresh(suite)
    return _suite_to_response(suite)


@router.get(
    "/policies/test-suites/{suite_id}",
    response_model=PolicyTestSuiteRecordResponse,
    dependencies=[Depends(require_scope("policies:read"))],
)
async def get_policy_test_suite(
    suite_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyTestSuiteRecordResponse:
    result = await session.execute(
        select(PolicyTestSuite).where(
            PolicyTestSuite.id == suite_id,
            PolicyTestSuite.org_id == request.state.org_id,
        )
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Policy test suite not found.")
    return _suite_to_response(suite)


@router.delete(
    "/policies/test-suites/{suite_id}",
    status_code=204,
    dependencies=[Depends(require_scope("policies:write"))],
)
async def delete_policy_test_suite(
    suite_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(PolicyTestSuite).where(
            PolicyTestSuite.id == suite_id,
            PolicyTestSuite.org_id == request.state.org_id,
        )
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Policy test suite not found.")
    await session.delete(suite)
    await session.flush()


@router.post(
    "/policies/test-suites/{suite_id}/run",
    response_model=PolicyTestSuiteResponse,
    dependencies=[Depends(require_scope("policies:read"))],
)
async def run_policy_test_suite(
    suite_id: uuid.UUID,
    request: Request,
    format: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PolicyTestSuiteResponse | PlainTextResponse:
    result = await session.execute(
        select(PolicyTestSuite).where(
            PolicyTestSuite.id == suite_id,
            PolicyTestSuite.org_id == request.state.org_id,
        )
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Policy test suite not found.")

    test_cases = list(suite.test_cases or [])
    suite_request = PolicyTestSuiteRequest(
        test_cases=[PolicyTestCase.model_validate(test_case) for test_case in test_cases]
    )
    run_result = await _run_policy_test_suite(session, request.state.org_id, suite_request)

    if format == "github_actions":
        status_code = 200 if run_result.failed == 0 else 422
        return PlainTextResponse(_to_github_actions_output(run_result), status_code=status_code)
    return run_result


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    dependencies=[Depends(require_scope("policies:read"))],
)
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


@router.patch(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    dependencies=[Depends(require_scope("policies:write"))],
)
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


@router.patch(
    "/policies/{policy_id}/activate",
    response_model=PolicyResponse,
    dependencies=[Depends(require_scope("policies:write"))],
)
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


@router.patch(
    "/policies/{policy_id}/archive",
    response_model=PolicyResponse,
    dependencies=[Depends(require_scope("policies:write"))],
)
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
    dependencies=[Depends(require_scope("policies:read"))],
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
    dependencies=[Depends(require_scope("policies:write"))],
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


@router.delete(
    "/policies/{policy_id}",
    status_code=204,
    dependencies=[Depends(require_scope("policies:write"))],
)
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
