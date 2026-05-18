"""Approval creation and management service."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ApprovalRequest
from app.services.temporal_service import start_approval_workflow

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


def _resolve_sla_hours(sla_hours: int | None) -> int:
    """Clamp/default a caller-supplied SLA to the configured bounds.

    Negative or zero values fall back to the configured default so a bad
    request can never produce an already-expired approval.
    """
    if sla_hours is None or sla_hours <= 0:
        return settings.default_sla_hours
    return min(sla_hours, settings.max_sla_hours)


async def create_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object] | None = None,
    approver_email: str | None = None,
    sla_hours: int | None = None,
    background_tasks: "BackgroundTasks | None" = None,
) -> ApprovalRequest:
    """Create a new pending approval request and start a Temporal workflow.

    Temporal is optional: if TEMPORAL_HOST is not set or unreachable, the
    approval is tracked by DB row only — the approval flow still works via
    email links and API polling.

    Slack notification is enqueued via background_tasks (if provided) so it
    fires AFTER the transaction commits — not before (S3: prevents phantom
    Slack messages for rolled-back approvals).

    sla_hours controls how long the approval stays pending. When unset, the
    operator-configured default (settings.default_sla_hours, 48h) is used.
    The value is capped at settings.max_sla_hours (168h / 7d) and persisted
    on the row so dashboards and reminders can read the active SLA.
    """
    effective_sla = _resolve_sla_hours(sla_hours)
    now = datetime.now(UTC)
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        agent_id=agent_id,
        action=action,
        resource=resource,
        context=context,
        status="pending",
        approver_email=approver_email,
        sla_hours=effective_sla,
        expires_at=now + timedelta(hours=effective_sla),
        workflow_status="running",
        workflow_fallback_mode="none",
        workflow_last_transition_at=now,
    )
    session.add(approval)
    await session.flush()

    # Start durable Temporal workflow (no-op if Temporal not configured).
    # SLA is forwarded so the workflow's wait_condition matches the DB row.
    workflow_start = await start_approval_workflow(approval.id, sla_hours=effective_sla)
    approval.workflow_fallback_mode = workflow_start.fallback_mode
    if workflow_start.error:
        approval.workflow_last_error = workflow_start.error
    if workflow_start.workflow_id:
        approval.temporal_run_id = workflow_start.workflow_id
    approval.workflow_mode = "temporal" if workflow_start.workflow_id else "db_only"  # type: ignore[attr-defined]
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
