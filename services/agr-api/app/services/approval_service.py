"""Approval creation and management service."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest
from app.services.temporal_service import start_approval_workflow

logger = logging.getLogger(__name__)


async def create_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object] | None = None,
    approver_email: str | None = None,
) -> ApprovalRequest:
    """Create a new pending approval request and start a Temporal workflow.

    Temporal is optional: if TEMPORAL_HOST is not set or unreachable, the
    approval is tracked by DB row only — the approval flow still works via
    email links and API polling.
    """
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        agent_id=agent_id,
        action=action,
        resource=resource,
        context=context,
        status="pending",
        approver_email=approver_email,
        expires_at=datetime.now(UTC) + timedelta(hours=48),
    )
    session.add(approval)
    await session.flush()

    # Start durable Temporal workflow (no-op if Temporal not configured)
    workflow_id = await start_approval_workflow(approval.id)
    if workflow_id:
        approval.temporal_run_id = workflow_id
        await session.flush()

    logger.info("Created approval request %s for %s/%s", approval.id, action, resource)
    return approval
