"""Audit trail query endpoint."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AuditEvent
from app.schemas import AuditEventResponse

router = APIRouter(prefix="/v1")


def _event_to_response(e: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=str(e.id),
        org_id=str(e.org_id),
        sequence_num=e.sequence_num,
        event_type=e.event_type,
        agent_id=e.agent_id,
        action=e.action,
        resource=e.resource,
        decision=e.decision,
        policy_id=str(e.policy_id) if e.policy_id else None,
        approval_id=str(e.approval_id) if e.approval_id else None,
        payload=e.payload,
        prev_hash=e.prev_hash,
        entry_hash=e.entry_hash,
        recorded_at=e.recorded_at,
    )


@router.get("/audit", response_model=list[AuditEventResponse])
async def list_audit_events(
    request: Request,
    session: AsyncSession = Depends(get_session),
    event_type: str | None = None,
    agent_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventResponse]:
    org_id: uuid.UUID = request.state.org_id
    stmt = select(AuditEvent).where(AuditEvent.org_id == org_id)

    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if agent_id:
        stmt = stmt.where(AuditEvent.agent_id == agent_id)
    if start_date:
        stmt = stmt.where(AuditEvent.recorded_at >= start_date)
    if end_date:
        stmt = stmt.where(AuditEvent.recorded_at <= end_date)

    stmt = stmt.order_by(AuditEvent.sequence_num.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    events = result.scalars().all()
    return [_event_to_response(e) for e in events]
