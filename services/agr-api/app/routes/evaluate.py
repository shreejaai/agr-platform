"""POST /v1/evaluate — THE core endpoint."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import update as sa_update

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Organization

from sqlalchemy import or_

from app.database import get_session
from app.schemas import ErrorResponse, EvaluateRequest, EvaluateResponse
from app.services.approval_service import create_approval_request
from app.services.audit_service import create_audit_event
from app.services.cedar_service import evaluate_request
from app.services.notification_service import send_approval_email
from app.services.redis_service import (
    get_cached_eval,
    rate_limit_incr,
    set_cached_eval,
    sync_eval_count_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def evaluate(
    body: EvaluateRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> EvaluateResponse | Response:
    org: Organization = request.state.org
    org_id: uuid.UUID = request.state.org_id

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
        if reset_result.rowcount > 0:
            org.eval_count = 0
            org.eval_week_start = now_utc

    # -------------------------------------------------------------------------
    # Rate limit — Redis INCR (fast path); falls back to DB check if Redis down
    # -------------------------------------------------------------------------
    rate_limited, new_count = await rate_limit_incr(org_id, org.eval_limit, org.eval_count)

    if not rate_limited and org.eval_limit > 0 and org.eval_count >= org.eval_limit:
        # Redis unavailable path: new_count == org.eval_count, check DB value
        rate_limited = True

    if rate_limited:
        return Response(
            content=(
                '{"error":"eval_limit_exceeded",'
                f'"message":"You have reached your evaluation limit of {org.eval_limit}. '
                'Upgrade your plan for more evaluations.",'
                '"upgrade_url":"https://agr.dev/pricing"}'
            ),
            status_code=429,
            media_type="application/json",
        )

    # -------------------------------------------------------------------------
    # Cache lookup — skip Cedar + policy DB query on hit
    # -------------------------------------------------------------------------
    cached = await get_cached_eval(org_id, body.agent_id, body.action, body.resource, body.context)

    eval_id = str(uuid.uuid4())
    approval_id: str | None = None

    if cached and cached.get("decision") in ("ALLOW", "DENY"):
        decision = str(cached["decision"])
        reason = str(cached.get("reason", ""))
        policy_id = cached.get("policy_id")
        latency_ms = float(cached.get("latency_ms", 0))

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

        background_tasks.add_task(sync_eval_count_to_db, org_id)
        return EvaluateResponse(
            decision=decision,
            reason=reason,
            policy_id=str(policy_id) if policy_id else None,
            approval_id=None,
            latency_ms=latency_ms,
            eval_id=eval_id,
        )

    # -------------------------------------------------------------------------
    # Cedar evaluation (cache miss)
    # -------------------------------------------------------------------------
    result = await evaluate_request(
        session=session,
        org_id=org_id,
        agent_id=body.agent_id,
        action=body.action,
        resource=body.resource,
        context=body.context,
    )

    if result.decision == "APPROVAL_REQUIRED":
        approval = await create_approval_request(
            session=session,
            org_id=org_id,
            agent_id=body.agent_id,
            action=body.action,
            resource=body.resource,
            context=body.context,
            approver_email=body.approver_email,
        )
        approval_id = str(approval.id)
        background_tasks.add_task(send_approval_email, approval)

    event_type = (
        "APPROVAL_REQUESTED"
        if result.decision == "APPROVAL_REQUIRED"
        else f"TOOL_{result.decision}"
    )

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
        payload={"context": body.context, "eval_id": eval_id},
    )

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

    return EvaluateResponse(
        decision=result.decision,
        reason=result.reason,
        policy_id=result.policy_id,
        approval_id=approval_id,
        latency_ms=result.latency_ms,
        eval_id=eval_id,
    )
