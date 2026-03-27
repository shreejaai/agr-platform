"""Approval decision endpoints."""

import html as _html
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ApprovalRequest, ApprovalStep
from app.schemas import (
    ApprovalDecideRequest,
    ApprovalDecisionRequest,
    ApprovalEscalateRequest,
    ApprovalResponse,
    ApprovalStepCreate,
    ApprovalStepResponse,
)
from app.services.audit_service import create_audit_event
from app.services.notification_service import send_approval_email, verify_decision_token
from app.services.redis_service import check_decide_rate_limit
from app.services.temporal_service import signal_approval_escalation, signal_approval_workflow
from app.services.webhook_service import fire_approval_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["approvals"])


def _to_response(a: ApprovalRequest) -> ApprovalResponse:
    temporal_run_id = getattr(a, "temporal_run_id", None)
    return ApprovalResponse(
        id=str(a.id),
        org_id=str(a.org_id),
        agent_id=a.agent_id,
        action=a.action,
        resource=a.resource,
        context=a.context,
        status=a.status,
        approver_email=a.approver_email,
        decision_at=a.decision_at,
        expires_at=a.expires_at,
        quorum_type=a.quorum_type,
        sla_hours=a.sla_hours,
        escalation_email=a.escalation_email,
        created_at=a.created_at,
        workflow_mode="temporal" if temporal_run_id else "db_only",
        temporal_run_id=str(temporal_run_id) if temporal_run_id else None,
        workflow_status=a.workflow_status,
        workflow_last_error=a.workflow_last_error,
        workflow_last_transition_at=a.workflow_last_transition_at,
        workflow_fallback_mode=a.workflow_fallback_mode,
        workflow_escalated_at=a.workflow_escalated_at,
    )


async def _refresh_workflow_state(approval: ApprovalRequest, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    changed = False

    if approval.status in {"approved", "rejected"} and approval.workflow_status != "completed":
        approval.workflow_status = "completed"
        approval.workflow_last_transition_at = now
        changed = True

    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if (
        approval.status == "pending"
        and now > expires
        and approval.workflow_status in {"running", "escalated"}
    ):
        approval.workflow_status = "failed"
        timeout_message = "Approval expired without a recorded decision."
        if approval.workflow_last_error:
            if "expired" not in approval.workflow_last_error.lower():
                approval.workflow_last_error = f"{approval.workflow_last_error}; {timeout_message}"
        else:
            approval.workflow_last_error = timeout_message
        approval.workflow_last_transition_at = now
        if approval.workflow_fallback_mode == "none":
            approval.workflow_fallback_mode = "timeout_enforced"
        changed = True

    if changed:
        await session.flush()


async def _load_pending(
    approval_id: uuid.UUID, org_id: uuid.UUID, session: AsyncSession
) -> ApprovalRequest:
    """Load an approval scoped to the org, raise 404/409 as needed.

    Uses SELECT FOR UPDATE to prevent concurrent decision races — two simultaneous
    approve/reject calls would otherwise both pass the status check.
    """
    result = await session.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.org_id == org_id,
        )
        .with_for_update()
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    await _refresh_workflow_state(approval, session)
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval request already resolved with status '{approval.status}'.",
        )
    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if datetime.now(UTC) > expires:
        raise HTTPException(status_code=410, detail="Approval request has expired.")
    return approval


@router.get("/approvals", response_model=list[ApprovalResponse])
async def list_approvals(
    request: Request,
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
) -> list[ApprovalResponse]:
    org_id: uuid.UUID = request.state.org_id
    stmt = select(ApprovalRequest).where(ApprovalRequest.org_id == org_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc())
    result = await session.execute(stmt)
    approvals = result.scalars().all()
    for approval in approvals:
        await _refresh_workflow_state(approval, session)
    visible = approvals
    if status == "pending":
        visible = [approval for approval in approvals if approval.workflow_status != "failed"]
    return [_to_response(a) for a in visible]


# NOTE: must be registered before /{approval_id} so "decide" is not matched as a UUID
@router.get("/approvals/decide")
async def decide_via_email_get(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Render a confirmation page for one-click email approve/reject links."""
    parsed = verify_decision_token(token)
    if parsed is None:
        return Response(
            content=_html_page("Invalid or expired link", "error"),
            media_type="text/html",
            status_code=400,
        )
    approval_id_str, decision, token_ver = parsed
    try:
        approval_uuid = uuid.UUID(approval_id_str)
    except ValueError:
        return Response(
            content=_html_page("Invalid approval ID", "error"),
            media_type="text/html",
            status_code=400,
        )
    result = await session.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_uuid)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        return Response(
            content=_html_page("Approval request not found.", "error"),
            media_type="text/html",
            status_code=404,
        )
    if approval.status != "pending":
        return Response(
            content=_html_page(f"This request was already {approval.status}.", "info"),
            media_type="text/html",
            status_code=200,
        )
    # H3: reject tokens from before the last escalation
    if token_ver is not None and approval.token_version != token_ver:
        return Response(
            content=_html_page(
                "This link has been superseded. Check your email for the latest link.",
                "error",
            ),
            media_type="text/html",
            status_code=410,
        )

    verb = "Approve" if decision == "approved" else "Reject"
    color = "#16a34a" if decision == "approved" else "#dc2626"
    # C1: escape user-controlled fields to prevent XSS in the confirmation page
    safe_agent = _html.escape(str(approval.agent_id))
    safe_action = _html.escape(str(approval.action))
    safe_resource = _html.escape(str(approval.resource))
    # S4: token is placed in a hidden POST field, NOT in the action URL.
    # URL query params appear in server logs, browser history, and Referer headers —
    # putting a bearer token there leaks it. Hidden form fields are not logged.
    return Response(
        content=f"""
<html><body style="font-family:sans-serif;max-width:480px;margin:48px auto;padding:0 16px">
  <h2>Confirm {verb}</h2>
  <p><strong>Agent:</strong> {safe_agent}</p>
  <p><strong>Action:</strong> {safe_action}</p>
  <p><strong>Resource:</strong> {safe_resource}</p>
  <form method="POST" action="/v1/approvals/decide">
    <input type="hidden" name="token" value="{_html.escape(token)}">
    <button type="submit"
      style="background:{color};color:#fff;padding:12px 28px;border:none;
             border-radius:6px;font-size:16px;font-weight:600;cursor:pointer">
      Confirm {verb}
    </button>
  </form>
</body></html>""",
        media_type="text/html",
        status_code=200,
    )


@router.post("/approvals/decide")
async def decide_via_email_post(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    # S4: accept token from POST body (hidden form field) to keep it out of
    # server logs and browser history. Also accept query param for backward
    # compat with Slack button URLs already in the wild.
    token_body: str | None = Form(default=None, alias="token"),
    token_query: str | None = None,
    request: Request = None,  # type: ignore[assignment]
) -> Response:
    """Execute one-click approve/reject from email link (no auth required)."""
    # Prefer form body token; fall back to query param for Slack button links
    token = token_body or token_query
    if token is None and request is not None:
        token = request.query_params.get("token")
    if not token:
        return Response(
            content=_html_page("Missing token.", "error"),
            media_type="text/html",
            status_code=400,
        )
    parsed = verify_decision_token(token)
    if parsed is None:
        return Response(
            content=_html_page("Invalid or expired link.", "error"),
            media_type="text/html",
            status_code=400,
        )
    approval_id_str, decision, token_ver = parsed

    # M5: rate-limit this unauthenticated endpoint — max 10 attempts per
    # approval ID per 5 minutes to block automated abuse
    if await check_decide_rate_limit(approval_id_str):
        return Response(
            content=_html_page("Too many attempts. Please try again later.", "error"),
            media_type="text/html",
            status_code=429,
        )

    try:
        approval_uuid = uuid.UUID(approval_id_str)
    except ValueError:
        return Response(
            content=_html_page("Invalid approval ID.", "error"),
            media_type="text/html",
            status_code=400,
        )
    result = await session.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_uuid)
        .with_for_update()  # serialize concurrent email-link clicks to prevent double-decision
    )
    approval = result.scalar_one_or_none()
    if not approval:
        return Response(
            content=_html_page("Approval request not found.", "error"),
            media_type="text/html",
            status_code=404,
        )
    if approval.status != "pending":
        return Response(
            content=_html_page(f"This request was already {approval.status}.", "info"),
            media_type="text/html",
            status_code=200,
        )
    # H3: reject tokens from before the last escalation
    if token_ver is not None and approval.token_version != token_ver:
        return Response(
            content=_html_page(
                "This link has been superseded. Check your email for the latest link.",
                "error",
            ),
            media_type="text/html",
            status_code=410,
        )
    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if datetime.now(UTC) > expires:
        return Response(
            content=_html_page("This approval link has expired.", "error"),
            media_type="text/html",
            status_code=410,
        )

    approval.status = decision
    approval.decision_at = datetime.now(UTC)
    approval.workflow_status = "completed"
    approval.workflow_last_transition_at = approval.decision_at
    await session.flush()

    if approval.temporal_run_id:
        signal_result = await signal_approval_workflow(approval.temporal_run_id, decision)
        if not signal_result.delivered:
            approval.workflow_fallback_mode = "signal_retry_exhausted"
            approval.workflow_last_error = signal_result.error
            await session.flush()

    await create_audit_event(
        session=session,
        org_id=approval.org_id,
        event_type=f"APPROVAL_{decision.upper()}",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision=decision,
        approval_id=approval.id,
        payload={"decided_by": "email_link", "reason": ""},
    )

    background_tasks.add_task(
        fire_approval_webhook,
        approval.org_id,
        f"approval.{decision}",
        approval.id,
        approval.agent_id,
        approval.action,
        approval.resource,
        "email_link",
        "",
    )

    label = "approved" if decision == "approved" else "rejected"
    return Response(
        content=_html_page(
            f"'{approval.action}' on '{approval.resource}' has been {label}.",
            "success" if decision == "approved" else "rejected",
        ),
        media_type="text/html",
        status_code=200,
    )


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.org_id == org_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    await _refresh_workflow_state(approval, session)
    return _to_response(approval)


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    body: ApprovalDecideRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Unified approve/reject endpoint."""
    org_id: uuid.UUID = request.state.org_id
    approval = await _load_pending(approval_id, org_id, session)

    approval.status = body.decision
    approval.decision_at = datetime.now(UTC)
    approval.workflow_status = "completed"
    approval.workflow_last_transition_at = approval.decision_at
    await session.flush()

    if approval.temporal_run_id:
        signal_result = await signal_approval_workflow(approval.temporal_run_id, body.decision)
        if not signal_result.delivered:
            approval.workflow_fallback_mode = "signal_retry_exhausted"
            approval.workflow_last_error = signal_result.error
            await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type=f"APPROVAL_{body.decision.upper()}",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision=body.decision,
        approval_id=approval.id,
        payload={"decided_by": body.decided_by, "reason": body.reason},
    )

    background_tasks.add_task(
        fire_approval_webhook,
        org_id,
        f"approval.{body.decision}",
        approval.id,
        approval.agent_id,
        approval.action,
        approval.resource,
        body.decided_by,
        body.reason,
    )
    return _to_response(approval)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_request(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    org_id: uuid.UUID = request.state.org_id
    approval = await _load_pending(approval_id, org_id, session)

    approval.status = "approved"
    approval.decision_at = datetime.now(UTC)
    approval.workflow_status = "completed"
    approval.workflow_last_transition_at = approval.decision_at
    await session.flush()

    if approval.temporal_run_id:
        signal_result = await signal_approval_workflow(approval.temporal_run_id, "approved")
        if not signal_result.delivered:
            approval.workflow_fallback_mode = "signal_retry_exhausted"
            approval.workflow_last_error = signal_result.error
            await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="APPROVAL_APPROVED",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision="approved",
        approval_id=approval.id,
        payload={"decided_by": body.decided_by, "reason": body.reason},
    )

    background_tasks.add_task(
        fire_approval_webhook,
        org_id,
        "approval.approved",
        approval.id,
        approval.agent_id,
        approval.action,
        approval.resource,
        body.decided_by,
        body.reason,
    )
    return _to_response(approval)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_request(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    org_id: uuid.UUID = request.state.org_id
    approval = await _load_pending(approval_id, org_id, session)

    approval.status = "rejected"
    approval.decision_at = datetime.now(UTC)
    approval.workflow_status = "completed"
    approval.workflow_last_transition_at = approval.decision_at
    await session.flush()

    if approval.temporal_run_id:
        signal_result = await signal_approval_workflow(approval.temporal_run_id, "rejected")
        if not signal_result.delivered:
            approval.workflow_fallback_mode = "signal_retry_exhausted"
            approval.workflow_last_error = signal_result.error
            await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="APPROVAL_REJECTED",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision="rejected",
        approval_id=approval.id,
        payload={"decided_by": body.decided_by, "reason": body.reason},
    )

    background_tasks.add_task(
        fire_approval_webhook,
        org_id,
        "approval.rejected",
        approval.id,
        approval.agent_id,
        approval.action,
        approval.resource,
        body.decided_by,
        body.reason,
    )
    return _to_response(approval)


@router.post("/approvals/{approval_id}/escalate", response_model=ApprovalResponse)
async def escalate_approval(
    approval_id: uuid.UUID,
    body: ApprovalEscalateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Re-send approval email to a (new) approver email address.

    Updates approver_email and resends the notification. Returns 409 if
    the approval is no longer pending.
    Increments token_version so old email links sent to the previous
    approver are immediately invalidated (H3).
    """
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.org_id == org_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot escalate: approval already '{approval.status}'.",
        )

    approval.approver_email = body.approver_email
    # Invalidate old email tokens by bumping the version (H3)
    approval.token_version = (approval.token_version or 0) + 1
    approval.workflow_status = "escalated"
    approval.workflow_escalated_at = datetime.now(UTC)
    approval.workflow_last_transition_at = approval.workflow_escalated_at
    await session.flush()
    if approval.temporal_run_id:
        signal_result = await signal_approval_escalation(approval.temporal_run_id, body.approver_email)
        if not signal_result.delivered:
            approval.workflow_fallback_mode = "signal_retry_exhausted"
            approval.workflow_last_error = signal_result.error
            await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="APPROVAL_ESCALATED",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision="APPROVAL_REQUIRED",
        approval_id=approval.id,
        payload={"approver_email": body.approver_email},
    )
    # H1: send email as background task — don't block the response
    background_tasks.add_task(send_approval_email, approval)
    logger.info("Escalated approval %s to %s", approval_id, body.approver_email)
    return _to_response(approval)


@router.get("/approvals/{approval_id}/steps", response_model=list[ApprovalStepResponse])
async def list_approval_steps(
    approval_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[ApprovalStepResponse]:
    """List all approver steps for this approval request."""
    org_id: uuid.UUID = request.state.org_id
    # Verify ownership
    result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.org_id == org_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Approval request not found.")

    steps_result = await session.execute(
        select(ApprovalStep)
        .where(ApprovalStep.approval_id == approval_id, ApprovalStep.org_id == org_id)
        .order_by(ApprovalStep.created_at)
    )
    return [
        ApprovalStepResponse(
            id=str(s.id),
            approval_id=str(s.approval_id),
            approver_email=s.approver_email,
            status=s.status,
            decided_at=s.decided_at,
            created_at=s.created_at,
        )
        for s in steps_result.scalars().all()
    ]


@router.post("/approvals/{approval_id}/steps", response_model=ApprovalStepResponse, status_code=201)
async def add_approval_step(
    approval_id: uuid.UUID,
    body: ApprovalStepCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ApprovalStepResponse:
    """Add an approver step to a pending approval request."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.org_id == org_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot add step: approval is already '{approval.status}'.",
        )

    step = ApprovalStep(
        id=uuid.uuid4(),
        approval_id=approval_id,
        org_id=org_id,
        approver_email=body.approver_email,
    )
    session.add(step)
    await session.flush()
    await session.refresh(step)
    return ApprovalStepResponse(
        id=str(step.id),
        approval_id=str(step.approval_id),
        approver_email=step.approver_email,
        status=step.status,
        decided_at=step.decided_at,
        created_at=step.created_at,
    )


def _html_page(message: str, kind: str) -> str:
    colors = {"success": "#16a34a", "rejected": "#dc2626", "error": "#b91c1c", "info": "#2563eb"}
    color = colors.get(kind, "#111")
    style = (
        "font-family:sans-serif;max-width:480px;"
        "margin:48px auto;padding:0 16px;text-align:center"
    )
    return f"""
<html><body style="{style}">
  <p style="font-size:18px;color:{color}">{message}</p>
  <p style="color:#9ca3af;font-size:12px">You can close this window.</p>
</body></html>"""
