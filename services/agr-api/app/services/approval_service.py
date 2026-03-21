"""Approval creation and management service."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest
from app.services.temporal_service import start_approval_workflow

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


async def create_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object] | None = None,
    approver_email: str | None = None,
    background_tasks: "BackgroundTasks | None" = None,
) -> ApprovalRequest:
    """Create a new pending approval request and start a Temporal workflow.

    Temporal is optional: if TEMPORAL_HOST is not set or unreachable, the
    approval is tracked by DB row only — the approval flow still works via
    email links and API polling.

    Slack notification is enqueued via background_tasks (if provided) so it
    fires AFTER the transaction commits — not before (S3: prevents phantom
    Slack messages for rolled-back approvals).
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

    # S3: Slack fires as a background task so it runs after the transaction
    # commits. Calling it inline (before commit) caused phantom notifications
    # for approval rows that were subsequently rolled back.
    if background_tasks is not None:
        from app.services.slack_service import send_approval_slack

        background_tasks.add_task(send_approval_slack, approval)
    else:
        # Fallback for callers that don't pass BackgroundTasks (e.g., tests)
        from app.services.slack_service import send_approval_slack

        await send_approval_slack(approval)

    logger.info("Created approval request %s for %s/%s", approval.id, action, resource)
    return approval
