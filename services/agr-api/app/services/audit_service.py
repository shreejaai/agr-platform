"""Hash-chained append-only audit logger."""

import hashlib
import json
import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent

logger = logging.getLogger(__name__)


def compute_entry_hash(
    sequence_num: int,
    event_type: str,
    payload: dict[str, object] | None,
    prev_hash: str | None,
) -> str:
    """Compute SHA-256 hash for an audit entry.

    hash = SHA-256(sequence_num + event_type + json(payload) + prev_hash)
    """
    data = f"{sequence_num}:{event_type}:{json.dumps(payload, sort_keys=True, default=str)}:{prev_hash or ''}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def get_last_audit_event(
    session: AsyncSession, org_id: UUID
) -> AuditEvent | None:
    """Get the most recent audit event for an org to chain hashes."""
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.sequence_num.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_audit_event(
    session: AsyncSession,
    org_id: UUID,
    event_type: str,
    agent_id: str,
    action: str,
    resource: str,
    decision: str,
    policy_id: UUID | None = None,
    approval_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> AuditEvent:
    """Create a new hash-chained audit event."""
    last_event = await get_last_audit_event(session, org_id)
    prev_hash = last_event.entry_hash if last_event else None
    sequence_num = (last_event.sequence_num + 1) if last_event else 1

    entry_hash = compute_entry_hash(sequence_num, event_type, payload, prev_hash)

    event = AuditEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        sequence_num=sequence_num,
        event_type=event_type,
        agent_id=agent_id,
        action=action,
        resource=resource,
        decision=decision,
        policy_id=policy_id,
        approval_id=approval_id,
        payload=payload,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    session.add(event)
    await session.flush()
    return event
