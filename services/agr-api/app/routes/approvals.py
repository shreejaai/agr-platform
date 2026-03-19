"""Approval decision endpoints."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ApprovalRequest
from app.schemas import (
    ApprovalDecideRequest,
    ApprovalDecisionRequest,
    ApprovalEscalateRequest,
    ApprovalResponse,
)
from app.services.audit_service import create_audit_event
from app.services.notification_service import send_approval_email, verify_decision_token
from app.services.temporal_service import signal_approval_workflow
from app.services.webhook_service import fire_approval_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


def _to_response(a: ApprovalRequest) -> ApprovalResponse:
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
        created_at=a.created_at,
    )


async def _load_pending(
    approval_id: uuid.UUID, org_id: uuid.UUID, session: AsyncSession
) -> ApprovalRequest:
    """Load an approval scoped to the org, raise 404/409 as needed."""
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
            detail=f"Approval request already resolved with status '{approval.status}'.",
        )
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
    return [_to_response(a) for a in result.scalars().all()]


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
    approval_id_str, decision = parsed
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

    verb = "Approve" if decision == "approved" else "Reject"
    color = "#16a34a" if decision == "approved" else "#dc2626"
    return Response(
        content=f"""
<html><body style="font-family:sans-serif;max-width:480px;margin:48px auto;padding:0 16px">
  <h2>Confirm {verb}</h2>
  <p><strong>Agent:</strong> {approval.agent_id}</p>
  <p><strong>Action:</strong> {approval.action}</p>
  <p><strong>Resource:</strong> {approval.resource}</p>
  <form method="POST" action="/v1/approvals/decide?token={token}">
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
    token: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Execute one-click approve/reject from email link (no auth required)."""
    parsed = verify_decision_token(token)
    if parsed is None:
        return Response(
            content=_html_page("Invalid or expired link.", "error"),
            media_type="text/html",
            status_code=400,
        )
    approval_id_str, decision = parsed
    try:
        approval_uuid = uuid.UUID(approval_id_str)
    except ValueError:
        return Response(
            content=_html_page("Invalid approval ID.", "error"),
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

    approval.status = decision
    approval.decision_at = datetime.now(UTC)
    await session.flush()

    if approval.temporal_run_id:
        await signal_approval_workflow(approval.temporal_run_id, decision)

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
        session,
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
    await session.flush()

    if approval.temporal_run_id:
        await signal_approval_workflow(approval.temporal_run_id, body.decision)

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
        session,
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
    await session.flush()

    if approval.temporal_run_id:
        await signal_approval_workflow(approval.temporal_run_id, "approved")

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
        session,
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
    await session.flush()

    if approval.temporal_run_id:
        await signal_approval_workflow(approval.temporal_run_id, "rejected")

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
        session,
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
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Re-send approval email to a (new) approver email address.

    Updates approver_email and resends the notification. Returns 409 if
    the approval is no longer pending.
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
    await session.flush()
    await send_approval_email(approval)
    logger.info("Escalated approval %s to %s", approval_id, body.approver_email)
    return _to_response(approval)


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
