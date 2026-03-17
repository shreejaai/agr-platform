"""POST /v1/evaluate — THE core endpoint."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Organization
from app.schemas import ErrorResponse, EvaluateRequest, EvaluateResponse
from app.services.approval_service import create_approval_request
from app.services.audit_service import create_audit_event
from app.services.cedar_service import evaluate_request
from app.services.notification_service import send_approval_email

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

    if org.eval_limit > 0 and org.eval_count >= org.eval_limit:
        response.status_code = 429
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

    result = await evaluate_request(
        session=session,
        org_id=org_id,
        agent_id=body.agent_id,
        action=body.action,
        resource=body.resource,
        context=body.context,
    )

    eval_id = str(uuid.uuid4())
    approval_id: str | None = None

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

    event_type = f"TOOL_{result.decision}"
    if result.decision == "APPROVAL_REQUIRED":
        event_type = "APPROVAL_REQUESTED"

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

    await session.execute(
        update(Organization)
        .where(Organization.id == org_id)
        .values(eval_count=Organization.eval_count + 1)
    )

    return EvaluateResponse(
        decision=result.decision,
        reason=result.reason,
        policy_id=result.policy_id,
        approval_id=approval_id,
        latency_ms=result.latency_ms,
        eval_id=eval_id,
    )
