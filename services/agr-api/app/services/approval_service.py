"""Approval creation and management service."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest

logger = logging.getLogger(__name__)


async def create_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object] | None = None,
) -> ApprovalRequest:
    """Create a new pending approval request."""
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        agent_id=agent_id,
        action=action,
        resource=resource,
        context=context,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=48),
    )
    session.add(approval)
    await session.flush()
    logger.info("Created approval request %s for %s/%s", approval.id, action, resource)
    return approval
