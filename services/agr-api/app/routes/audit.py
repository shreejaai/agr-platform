"""Audit trail query and chain-verification endpoints."""

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.database import get_session
from app.models import AuditEvent
from app.schemas import AuditEventResponse, AuditSearchRequest, AuditVerifyResponse
from app.services.audit_service import compute_entry_hash

router = APIRouter(prefix="/v1", tags=["audit"])


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


def _apply_filters(
    stmt: Select[Any],
    org_id: uuid.UUID,
    event_type: str | None = None,
    agent_id: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    decision: str | None = None,
    policy_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> Select[Any]:
    """Apply common filter clauses to an AuditEvent SELECT statement."""
    stmt = stmt.where(AuditEvent.org_id == org_id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if agent_id:
        stmt = stmt.where(AuditEvent.agent_id == agent_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if resource:
        stmt = stmt.where(AuditEvent.resource == resource)
    if decision:
        stmt = stmt.where(AuditEvent.decision == decision)
    if policy_id:
        stmt = stmt.where(AuditEvent.policy_id == policy_id)
    if start_date:
        stmt = stmt.where(AuditEvent.recorded_at >= start_date)
    if end_date:
        stmt = stmt.where(AuditEvent.recorded_at <= end_date)
    return stmt


@router.get("/audit", response_model=list[AuditEventResponse])
async def list_audit_events(
    request: Request,
    session: AsyncSession = Depends(get_session),
    event_type: str | None = None,
    agent_id: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    decision: str | None = None,
    policy_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventResponse]:
    org_id: uuid.UUID = request.state.org_id
    stmt = _apply_filters(
        select(AuditEvent),
        org_id,
        event_type=event_type,
        agent_id=agent_id,
        action=action,
        resource=resource,
        decision=decision,
        policy_id=policy_id,
        start_date=start_date,
        end_date=end_date,
    )
    stmt = stmt.order_by(AuditEvent.sequence_num.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [_event_to_response(e) for e in result.scalars().all()]


@router.post("/audit/search", response_model=list[AuditEventResponse])
async def search_audit_events(
    body: AuditSearchRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[AuditEventResponse]:
    """POST-body alternative to GET /audit for complex filter combinations.

    Useful when query-string length is a concern or when building structured
    search UIs that prefer sending JSON.
    """
    org_id: uuid.UUID = request.state.org_id
    stmt = _apply_filters(
        select(AuditEvent),
        org_id,
        event_type=body.event_type,
        agent_id=body.agent_id,
        action=body.action,
        resource=body.resource,
        decision=body.decision,
        policy_id=body.policy_id,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    stmt = stmt.order_by(AuditEvent.sequence_num.desc()).offset(body.offset).limit(body.limit)
    result = await session.execute(stmt)
    return [_event_to_response(e) for e in result.scalars().all()]


_CSV_FIELDS = [
    "id", "sequence_num", "event_type", "agent_id", "action",
    "resource", "decision", "policy_id", "approval_id", "recorded_at",
]
_EXPORT_PAGE_SIZE = 1000
_EXPORT_MAX_ROWS = 50_000


@router.post("/audit/export")
async def export_audit_events(
    body: AuditSearchRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream audit events matching filters as a CSV file.

    Streams rows in pages of 1 000 to avoid loading the full result set into
    memory. Caps at 50 000 rows; use offset/pagination for larger exports.
    """
    org_id: uuid.UUID = request.state.org_id

    async def _generate() -> Any:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()

        exported = 0
        page_offset = body.offset
        while exported < _EXPORT_MAX_ROWS:
            batch = min(_EXPORT_PAGE_SIZE, _EXPORT_MAX_ROWS - exported)
            stmt = _apply_filters(
                select(AuditEvent),
                org_id,
                event_type=body.event_type,
                agent_id=body.agent_id,
                action=body.action,
                resource=body.resource,
                decision=body.decision,
                policy_id=body.policy_id,
                start_date=body.start_date,
                end_date=body.end_date,
            )
            stmt = stmt.order_by(AuditEvent.sequence_num.asc()).offset(page_offset).limit(batch)
            result = await session.execute(stmt)
            events = result.scalars().all()
            if not events:
                break
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
            for e in events:
                writer.writerow({
                    "id": str(e.id),
                    "sequence_num": e.sequence_num,
                    "event_type": e.event_type,
                    "agent_id": e.agent_id,
                    "action": e.action,
                    "resource": e.resource,
                    "decision": e.decision,
                    "policy_id": str(e.policy_id) if e.policy_id else "",
                    "approval_id": str(e.approval_id) if e.approval_id else "",
                    "recorded_at": e.recorded_at.isoformat(),
                })
            yield buf.getvalue()
            exported += len(events)
            page_offset += len(events)
            if len(events) < batch:
                break

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
    )


_VERIFY_PAGE_SIZE = 1000  # rows per batch — prevents OOM on large audit logs
_VERIFY_MAX_EVENTS = 100_000  # hard ceiling; raise 400 above this


@router.get("/audit/verify", response_model=AuditVerifyResponse)
async def verify_audit_chain(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=_VERIFY_MAX_EVENTS, le=_VERIFY_MAX_EVENTS, ge=1),
) -> AuditVerifyResponse:
    """Re-compute and verify the SHA-256 hash chain for this org's audit log.

    Walks events in sequence order in pages of 1 000 rows to prevent OOM on
    large audit logs. Stops at `limit` events (default/max = 100 000).
    Returns the first invalid sequence number if a break is found.
    """
    org_id: uuid.UUID = request.state.org_id

    prev_hash: str | None = None
    total_verified = 0
    offset = 0

    while True:
        batch_limit = min(_VERIFY_PAGE_SIZE, limit - total_verified)
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id)
            .order_by(AuditEvent.sequence_num.asc())
            .offset(offset)
            .limit(batch_limit)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            break

        for event in events:
            expected = compute_entry_hash(
                event.sequence_num,
                event.event_type,
                event.payload,
                prev_hash,
            )
            if expected != event.entry_hash:
                return AuditVerifyResponse(
                    valid=False,
                    total=total_verified + 1,
                    first_invalid_sequence=event.sequence_num,
                )
            prev_hash = event.entry_hash
            total_verified += 1

        offset += len(events)
        if len(events) < batch_limit:
            break

    return AuditVerifyResponse(valid=True, total=total_verified)
