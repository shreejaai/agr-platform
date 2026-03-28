"""POST /v1/evaluate — THE core endpoint."""

from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import update as sa_update

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Organization

from sqlalchemy import or_

from app.config import settings
from app.database import get_session
from app.middleware.auth import require_scope
from app.middleware.tracing import format_traceparent, get_tracer
from app.schemas import (
    ComplianceFindingResponse,
    DecisionTrace,
    EngineMode,
    ErrorResponse,
    EvaluateRequest,
    EvaluateResponse,
)
from app.services.anomaly_service import is_new_action, record_action
from app.services.approval_service import create_approval_request
from app.services.audit_service import create_audit_event
from app.services.cedar_service import evaluate_request
from app.services.compliance_service import ComplianceContext, get_registry
from app.services.notification_service import send_approval_email
from app.services.redis_service import (
    get_cached_eval,
    get_idempotent_response,
    increment_eval_count,
    rate_limit_incr,
    set_cached_eval,
    set_idempotent_response,
    sync_eval_count_to_db,
)
from app.services.risk_service import RiskResult, compute_risk_score
from app.services.stream_service import publish
from app.services.usage_service import (
    determine_quota_status,
    record_evaluation_usage,
    should_emit_soft_limit_warning,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["evaluate"])


def _engine_mode(policy_source: str, fallback_used: bool) -> EngineMode:
    if policy_source == "cache":
        return "cache"
    if fallback_used or policy_source == "no_policies":
        return "python_fallback"
    return "cedar_cli"


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    dependencies=[Depends(require_scope("evaluate:write"))],
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def evaluate(
    body: EvaluateRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> EvaluateResponse:
    org: Organization = request.state.org
    org_id: uuid.UUID = request.state.org_id
    idempotency_key = request.headers.get("Idempotency-Key")

    if idempotency_key:
        replayed = await get_idempotent_response(org_id, idempotency_key)
        if replayed is not None:
            replayed_response = EvaluateResponse.model_validate(
                {**replayed, "idempotency_replayed": True}
            )
            response.headers["X-Idempotency-Replayed"] = "true"
            response.headers["X-AGR-Engine"] = replayed_response.engine_mode
            return replayed_response

    # -------------------------------------------------------------------------
    # Weekly reset — atomic single UPDATE prevents concurrent reset races (C2+C4)
    # -------------------------------------------------------------------------
    now_utc = datetime.now(UTC)
    week_threshold = now_utc - timedelta(days=7)

    if org.eval_limit > 0:
        from app.models import Organization as OrgModel

        reset_result = await session.execute(
            sa_update(OrgModel)
            .where(
                OrgModel.id == org_id,
                or_(
                    OrgModel.eval_week_start.is_(None),
                    OrgModel.eval_week_start < week_threshold,
                ),
            )
            .values(eval_count=0, eval_week_start=now_utc)
            .execution_options(synchronize_session=False)
        )
        if reset_result.rowcount > 0:  # type: ignore[attr-defined]
            org.eval_count = 0
            org.eval_week_start = now_utc

    # -------------------------------------------------------------------------
    # Usage counting / quota enforcement
    # -------------------------------------------------------------------------
    if org.eval_soft_limit_enabled:
        rate_limited = False
        new_count = await increment_eval_count(org_id, org.eval_count)
    else:
        rate_limited, new_count = await rate_limit_incr(org_id, org.eval_limit, org.eval_count)
        if not rate_limited and org.eval_limit > 0 and new_count >= org.eval_limit:
            rate_limited = True

        if rate_limited:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "eval_limit_exceeded",
                    "message": (
                        f"You have reached your evaluation limit of {org.eval_limit}. "
                        "Upgrade your plan for more evaluations."
                    ),
                    "upgrade_url": "https://agr.dev/pricing",
                },
            )

    org.eval_count = new_count
    quota_status = determine_quota_status(
        total_evaluations=new_count,
        eval_limit=org.eval_limit,
        warning_threshold_pct=org.eval_warning_threshold_pct,
        soft_limit_enabled=org.eval_soft_limit_enabled,
    )
    response.headers["X-AGR-Usage-State"] = quota_status.quota_state
    response.headers["X-AGR-Usage-Count"] = str(new_count)
    response.headers["X-AGR-Usage-Limit"] = str(org.eval_limit)
    if quota_status.warning_message:
        response.headers["X-AGR-Usage-Warning"] = quota_status.warning_message
    if should_emit_soft_limit_warning(org, quota_status):
        org.usage_last_warned_count = new_count
        org.usage_soft_limit_warning_sent_at = now_utc

    from app.models import Organization as OrgModel

    await session.execute(
        sa_update(OrgModel)
        .where(OrgModel.id == org_id)
        .values(
            eval_count=new_count,
            usage_last_warned_count=org.usage_last_warned_count,
            usage_soft_limit_warning_sent_at=org.usage_soft_limit_warning_sent_at,
        )
        .execution_options(synchronize_session=False)
    )

    await record_evaluation_usage(session, org_id, body.agent_id, now_utc)

    # -------------------------------------------------------------------------
    # Cache lookup — skip Cedar + policy DB query on hit
    # -------------------------------------------------------------------------
    tracer = get_tracer()
    cache_span_cm = tracer.start_as_current_span("redis.cache_lookup") if tracer else nullcontext()
    with cache_span_cm as cache_span:
        cached = await get_cached_eval(
            org_id, body.agent_id, body.action, body.resource, body.context
        )
        if cache_span is not None:
            cache_span.set_attribute("cache.hit", bool(cached))

    eval_id = str(uuid.uuid4())
    approval_id: str | None = None
    anomaly_detected = False
    anomaly_flags: list[str] = []

    if cached and cached.get("decision") in ("ALLOW", "DENY"):
        decision = str(cached["decision"])
        reason = str(cached.get("reason", ""))
        policy_id = cached.get("policy_id")
        latency_ms = float(cached.get("latency_ms") or 0)  # type: ignore[arg-type]
        response.headers["X-AGR-Engine"] = "cache"
        if decision == "ALLOW":
            anomaly_detected = await is_new_action(str(org_id), body.agent_id, body.action)
            if anomaly_detected:
                anomaly_flags.append("new_action")
                logger.warning(
                    "Agent %s calling new action %s — not seen in baseline",
                    body.agent_id,
                    body.action,
                )
            background_tasks.add_task(
                record_action, str(org_id), body.agent_id, body.action, body.resource
            )

        await create_audit_event(
            session=session,
            org_id=org_id,
            event_type=f"TOOL_{decision}",
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            decision=decision,
            policy_id=uuid.UUID(str(policy_id)) if policy_id else None,
            payload={"context": body.context, "eval_id": eval_id, "cached": True},
        )

        background_tasks.add_task(
            publish,
            str(org_id),
            {
                "eval_id": eval_id,
                "agent_id": body.agent_id,
                "action": body.action,
                "resource": body.resource,
                "decision": decision,
                "risk_score": None,
                "risk_level": None,
                "policy_source": "cache",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        background_tasks.add_task(sync_eval_count_to_db, org_id)
        cached_response = EvaluateResponse(
            decision=decision,
            reason=reason,
            policy_id=str(policy_id) if policy_id else None,
            approval_id=None,
            latency_ms=latency_ms,
            eval_id=eval_id,
            engine_mode="cache",
            anomaly_detected=anomaly_detected,
            anomaly_flags=anomaly_flags,
            decision_trace=DecisionTrace(
                policy_source="cache",
                matched_policy_id=str(policy_id) if policy_id else None,
                cedar_decision=decision,
                risk_override=False,
            ),
        )
        if idempotency_key:
            await set_idempotent_response(org_id, idempotency_key, cached_response.model_dump())
        return cached_response

    # -------------------------------------------------------------------------
    # Cedar evaluation (cache miss)
    # -------------------------------------------------------------------------
    cedar_span = None
    cedar_span_cm = tracer.start_as_current_span("cedar.evaluate") if tracer else nullcontext()
    with cedar_span_cm as span:
        cedar_span = span
        result = await evaluate_request(
            session=session,
            org_id=org_id,
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            context=body.context,
        )
    response.headers["X-AGR-Engine"] = _engine_mode(result.policy_source, result.fallback_used)

    if result.fallback_used and settings.cedar_require_cli:
        raise HTTPException(
            status_code=503,
            detail="Cedar CLI unavailable. Set CEDAR_REQUIRE_CLI=false to allow fallback.",
        )

    # Capture raw policy engine decision before risk scoring can override it
    cedar_decision = result.decision

    # -------------------------------------------------------------------------
    # Agent trust_level lookup — used by risk scoring (Task 8)
    # -------------------------------------------------------------------------
    from sqlalchemy import select as sa_select

    from app.models import Agent as AgentModel
    from app.models import OrgComplianceConfig, OrgRiskConfig

    agent_trust_level: str | None = None
    agent_row = await session.execute(
        sa_select(AgentModel.trust_level).where(
            AgentModel.org_id == org_id,
            AgentModel.agent_id == body.agent_id,
        )
    )
    agent_trust_row = agent_row.one_or_none()
    if agent_trust_row is not None:
        agent_trust_level = agent_trust_row[0]

    # Load per-org risk weights if configured
    risk_cfg_row = await session.execute(
        sa_select(OrgRiskConfig).where(OrgRiskConfig.org_id == org_id)
    )
    risk_cfg = risk_cfg_row.scalar_one_or_none()
    org_weights: dict[str, float] | None = None
    org_allow_max: int = settings.risk_thresholds_allow_max
    org_approval_max: int = settings.risk_thresholds_approval_max
    if risk_cfg is not None:
        org_weights = {
            "action_severity": risk_cfg.weight_action_severity,
            "context_signals": risk_cfg.weight_context_signals,
            "rate_pattern": risk_cfg.weight_rate_pattern,
            "agent_trust": risk_cfg.weight_agent_trust,
            "amount_scale": risk_cfg.weight_amount_scale,
            "resource_sensitivity": risk_cfg.weight_resource_sensitivity,
        }
        org_allow_max = risk_cfg.threshold_allow_max
        org_approval_max = risk_cfg.threshold_approval_max

    # -------------------------------------------------------------------------
    # Risk scoring — runs after Cedar; can upgrade ALLOW to APPROVAL_REQUIRED/DENY
    # Cedar DENY always wins; risk scoring only affects ALLOW decisions.
    # -------------------------------------------------------------------------
    risk: RiskResult | None = None
    if settings.risk_scoring_enabled:
        risk = compute_risk_score(
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            context=body.context,
            eval_count=new_count,
            eval_limit=org.eval_limit,
            trust_level=agent_trust_level,
            weights=org_weights,
        )
        # Only override if Cedar said ALLOW — DENY/APPROVAL_REQUIRED are final
        if result.decision == "ALLOW":
            if risk.score > org_approval_max:
                result.decision = "DENY"
                result.reason = (
                    f"Risk score {risk.score}/100 ({risk.level}) exceeds threshold "
                    f"{org_approval_max}. Action denied."
                )
            elif risk.score > org_allow_max:
                result.decision = "APPROVAL_REQUIRED"
                result.reason = (
                    f"Risk score {risk.score}/100 ({risk.level}) requires human approval. "
                    f"Threshold is {org_allow_max}."
                )
    if cedar_span is not None:
        cedar_span.set_attribute("agr.agent_id", body.agent_id)
        cedar_span.set_attribute("agr.action", body.action)
        cedar_span.set_attribute("agr.decision", result.decision)
        cedar_span.set_attribute("agr.policy_source", result.policy_source)
        cedar_span.set_attribute("agr.risk_score", risk.score if risk else 0)
        traceparent = format_traceparent(cedar_span)
        if traceparent is not None:
            response.headers["traceparent"] = traceparent

    # -------------------------------------------------------------------------
    # Compliance hooks — fail-open on errors; enforce-mode plugins can block
    # -------------------------------------------------------------------------
    compliance_findings: list[dict[str, object]] | None = None
    compliance_blocked = False
    deny_reason: str | None = None
    try:
        config_rows = await session.execute(
            sa_select(OrgComplianceConfig).where(OrgComplianceConfig.org_id == org_id)
        )
        enforcement_modes = {
            row.plugin_id: row.enforcement_mode for row in config_rows.scalars().all()
        }
        comp_ctx = ComplianceContext(
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
        comp_result = await get_registry().run_all(comp_ctx, enforcement_modes=enforcement_modes)
        compliance_findings = comp_result.to_dict() if comp_result.findings else None
        if comp_result.blocking_finding is not None:
            compliance_blocked = True
            result.decision = "DENY"
            deny_reason = (
                f"Compliance enforcement blocked: [{comp_result.blocking_finding.plugin_id}] "
                f"{comp_result.blocking_finding.message}"
            )
            result.reason = deny_reason
    except Exception as exc:
        logger.warning("Compliance hooks failed (ignoring): %s", exc)

    if result.decision == "APPROVAL_REQUIRED":
        approval = await create_approval_request(
            session=session,
            org_id=org_id,
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            context=body.context,
            approver_email=body.approver_email,
            background_tasks=background_tasks,  # S3: Slack fires post-commit
        )
        approval_id = str(approval.id)
        background_tasks.add_task(send_approval_email, approval)

    event_type = (
        "APPROVAL_REQUESTED"
        if result.decision == "APPROVAL_REQUIRED"
        else f"TOOL_{result.decision}"
    )

    if result.decision == "ALLOW":
        anomaly_detected = await is_new_action(str(org_id), body.agent_id, body.action)
        if anomaly_detected:
            anomaly_flags.append("new_action")
            logger.warning(
                "Agent %s calling new action %s — not seen in baseline",
                body.agent_id,
                body.action,
            )
        background_tasks.add_task(
            record_action, str(org_id), body.agent_id, body.action, body.resource
        )

    extra_payload: dict[str, object] = {
        "policy_source": result.policy_source,
        "fallback_used": result.fallback_used,
    }
    if result.fallback_used and result.fallback_reason:
        extra_payload["fallback_reason"] = result.fallback_reason
    if risk is not None:
        extra_payload.update(
            {
                "risk_score": risk.score,
                "risk_level": risk.level,
                "risk_factors": risk.factors,
            }
        )
    if compliance_findings:
        extra_payload["compliance_findings"] = compliance_findings
    extra_payload["compliance_blocked"] = compliance_blocked
    extra_payload["compliance_block_reason"] = deny_reason

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type=event_type,
        agent_id=body.agent_id,
        action=body.action,
        resource=body.resource,
        decision=result.decision,
        policy_id=uuid.UUID(result.policy_id) if result.policy_id else None,
        approval_id=uuid.UUID(approval_id) if approval_id else None,
        payload={"context": body.context, "eval_id": eval_id, **extra_payload},
    )
    background_tasks.add_task(
        publish,
        str(org_id),
        {
            "eval_id": eval_id,
            "agent_id": body.agent_id,
            "action": body.action,
            "resource": body.resource,
            "decision": result.decision,
            "risk_score": risk.score if risk else None,
            "risk_level": risk.level if risk else None,
            "policy_source": result.policy_source,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # Record Prometheus metrics (non-blocking, fail-open)
    try:
        from app.services.metrics_service import record_evaluation

        record_evaluation(result.decision, risk.score if risk else None)
    except Exception:
        pass

    # Cache ALLOW/DENY results; sync DB eval_count in background
    background_tasks.add_task(
        set_cached_eval,
        org_id,
        body.agent_id,
        body.action,
        body.resource,
        body.context,
        {
            "decision": result.decision,
            "reason": result.reason,
            "policy_id": result.policy_id,
            "latency_ms": result.latency_ms,
        },
    )
    background_tasks.add_task(sync_eval_count_to_db, org_id)

    api_response = EvaluateResponse(
        decision=result.decision,
        reason=result.reason,
        policy_id=result.policy_id,
        approval_id=approval_id,
        latency_ms=result.latency_ms,
        eval_id=eval_id,
        engine_mode=_engine_mode(result.policy_source, result.fallback_used),
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        risk_factors=risk.factors if risk else None,
        compliance_findings=cast(list[ComplianceFindingResponse] | None, compliance_findings),
        compliance_block=compliance_blocked,
        compliance_reason=deny_reason if compliance_blocked else None,
        compliance_blocked=compliance_blocked,
        anomaly_detected=anomaly_detected,
        anomaly_flags=anomaly_flags,
        decision_trace=DecisionTrace(
            policy_source=result.policy_source,
            matched_policy_id=result.policy_id,
            cedar_decision=cedar_decision,
            risk_score=risk.score if risk else None,
            risk_level=risk.level if risk else None,
            risk_override=risk is not None and result.decision != cedar_decision,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
        ),
    )
    if idempotency_key:
        await set_idempotent_response(org_id, idempotency_key, api_response.model_dump())
    return api_response
