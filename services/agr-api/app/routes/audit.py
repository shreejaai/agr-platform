"""Audit trail query and chain-verification endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.database import get_session
from app.middleware.auth import require_scope
from app.models import AuditEvent
from app.schemas import (
    AuditEventResponse,
    AuditExportJobResponse,
    AuditSearchRequest,
    AuditVerifyResponse,
    ReplayRequest,
    ReplayResponse,
)
from app.services.audit_service import (
    compute_entry_hash,
    get_audit_export_job,
    start_audit_export_job,
    stream_audit_events,
)
from app.services.replay_service import replay_evaluation

router = APIRouter(
    prefix="/v1", tags=["audit"], dependencies=[Depends(require_scope("audit:read"))]
)


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


@router.post("/audit/export", response_model=None)
async def export_audit_events(
    body: AuditSearchRequest,
    request: Request,
    format: Literal["json", "csv"] = "csv",
    async_export: bool = False,
    session: AsyncSession = Depends(get_session),
) -> Response:
    org_id: uuid.UUID = request.state.org_id
    if async_export:
        job = await start_audit_export_job(org_id, body.model_dump(), format)
        payload = AuditExportJobResponse(job_id=job.job_id, status="pending", format=format)
        return JSONResponse(status_code=202, content=payload.model_dump())

    filename = f'audit_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.{format}'
    media_type = "application/json" if format == "json" else "text/csv"
    return StreamingResponse(
        stream_audit_events(session, org_id, body, format),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit/export/{job_id}", response_model=AuditExportJobResponse)
async def get_audit_export_status(
    job_id: str,
    request: Request,
) -> AuditExportJobResponse:
    org_id: uuid.UUID = request.state.org_id
    job = await get_audit_export_job(job_id, org_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Audit export job not found.")

    download_url = None
    if job.status == "ready" and job.file_path:
        download_url = str(request.url_for("download_audit_export", job_id=job_id))

    return AuditExportJobResponse(
        job_id=job.job_id,
        status=cast(Literal["pending", "ready", "failed"], job.status),
        format=cast(Literal["json", "csv"], job.format),
        download_url=download_url,
        error=job.error,
    )


@router.get("/audit/export/{job_id}/download", name="download_audit_export")
async def download_audit_export(job_id: str, request: Request) -> FileResponse:
    org_id: uuid.UUID = request.state.org_id
    job = await get_audit_export_job(job_id, org_id)
    if job is None or job.status != "ready" or job.file_path is None:
        raise HTTPException(status_code=404, detail="Audit export job not ready.")

    media_type = "application/json" if job.format == "json" else "text/csv"
    filename = f"audit_export_{job_id}.{job.format}"
    return FileResponse(job.file_path, media_type=media_type, filename=filename)


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
                try:
                    from app.services.metrics_service import record_audit_chain_break

                    record_audit_chain_break()
                except Exception:
                    pass
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


@router.post("/audit/{eval_id}/replay", response_model=ReplayResponse)
async def replay_audit_event(
    eval_id: str,
    body: ReplayRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ReplayResponse:
    return await replay_evaluation(session, request.state.org_id, eval_id, body.policy_ids)
