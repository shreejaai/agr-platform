"""Temporal activities for AGR approval workflows.

Activities perform side-effectful work (DB writes, email/Slack dispatch)
on behalf of deterministic workflows. Keep workflow code free of I/O —
all external calls live here.

W2.3: send_approval_reminder is invoked from `ApprovalWorkflow` halfway
through the SLA window. It is idempotent — the `reminder_sent_at` column
is checked under a row lock so concurrent or replay-driven invocations
never fan out duplicate notifications.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from temporalio import activity

from app.database import async_session_factory, set_session_rls
from app.models import ApprovalRequest
from app.services.audit_service import create_audit_event
from app.services.notification_service import send_approval_email
from app.services.slack_service import send_approval_slack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _dispatch_reminder(session: AsyncSession, approval_id_str: str) -> dict[str, object]:
    """Core reminder logic — load + idempotency check + dispatch + record.

    Extracted so unit tests can call it directly without a Temporal client.
    Returns a dict describing what was done; raises only on programmer errors.
    """
    try:
        approval_id = uuid.UUID(approval_id_str)
    except ValueError:
        return {"status": "invalid_id", "approval_id": approval_id_str}

    row = await session.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
    )
    approval = row.scalar_one_or_none()
    if approval is None:
        return {"status": "missing", "approval_id": approval_id_str}

    if approval.status != "pending":
        return {"status": "not_pending", "approval_id": approval_id_str}

    if approval.reminder_sent_at is not None:
        return {"status": "already_sent", "approval_id": approval_id_str}

    # Apply RLS context so the audit insert sees the right org.
    await set_session_rls(session, approval.org_id)

    # Mark first to claim idempotency under the row lock, then dispatch.
    approval.reminder_sent_at = datetime.now(UTC)
    await session.flush()

    # Best-effort delivery — failures are logged but never roll back the flag.
    # Re-arming reminders is a future enhancement; for now we accept "one shot".
    try:
        await send_approval_email(approval, is_reminder=True)
    except Exception:
        logger.exception("Reminder email failed for approval %s", approval.id)
    try:
        await send_approval_slack(approval)
    except Exception:
        logger.exception("Reminder Slack failed for approval %s", approval.id)

    await create_audit_event(
        session=session,
        org_id=approval.org_id,
        event_type="APPROVAL_REMINDER_SENT",
        agent_id=approval.agent_id,
        action=approval.action,
        resource=approval.resource,
        decision="APPROVAL_REQUIRED",
        approval_id=approval.id,
        payload={"reminder_sent_at": approval.reminder_sent_at.isoformat()},
    )
    return {"status": "sent", "approval_id": approval_id_str}


@activity.defn
async def send_approval_reminder(approval_id: str) -> dict[str, object]:
    """Temporal activity: send a single reminder for a pending approval.

    Opens its own DB session — workflows never share sessions with activities.
    """
    async with async_session_factory() as session:
        try:
            result = await _dispatch_reminder(session, approval_id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result
