"""Approval decision endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ApprovalRequest
from app.schemas import ApprovalDecisionRequest, ApprovalResponse
from app.services.audit_service import create_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


def _approval_to_response(a: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=str(a.id),
        org_id=str(a.org_id),
        agent_id=a.agent_id,
        action=a.action,
        resource=a.resource,
        context=a.context,
        status=a.status,
        expires_at=a.expires_at,
        created_at=a.created_at,
    )


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
    return [_approval_to_response(a) for a in approvals]


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_request(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
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
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval request already resolved with status '{approval.status}'.",
        )

    approval.status = "approved"
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

    return _approval_to_response(approval)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_request(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
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
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval request already resolved with status '{approval.status}'.",
        )

    approval.status = "rejected"
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

    return _approval_to_response(approval)
