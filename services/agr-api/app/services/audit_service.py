"""Hash-chained append-only audit logger."""

import asyncio
import contextlib
import csv
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.database import async_session_factory
from app.models import AuditEvent, AuditExportJobRecord

_MAX_PAYLOAD_BYTES = 64_000  # ~64 KB — prevents unbounded JSONB growth

logger = logging.getLogger(__name__)


@dataclass
class AuditExportJob:
    job_id: str
    format: str
    status: str = "pending"
    file_path: str | None = None
    error: str | None = None


def _record_to_job(record: AuditExportJobRecord) -> AuditExportJob:
    return AuditExportJob(
        job_id=str(record.id),
        format=record.format,
        status=record.status,
        file_path=record.file_path,
        error=record.error,
    )


_STREAM_BATCH_SIZE = 500


def compute_entry_hash(
    sequence_num: int,
    event_type: str,
    payload: dict[str, object] | None,
    prev_hash: str | None,
) -> str:
    """Compute SHA-256 hash for an audit entry.

    hash = SHA-256(sequence_num + event_type + json(payload) + prev_hash)
    """
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    data = f"{sequence_num}:{event_type}:{payload_json}:{prev_hash or ''}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def get_last_audit_event(session: AsyncSession, org_id: UUID) -> AuditEvent | None:
    """Get the most recent audit event for an org to chain hashes.

    Uses SELECT FOR UPDATE to serialize concurrent audit writes for the same org,
    preventing duplicate sequence numbers and hash chain corruption.
    Silently ignored on SQLite (used in tests).
    """
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.sequence_num.desc())
        .limit(1)
        .with_for_update()
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

    # L8: cap payload size to prevent unbounded JSONB growth in audit_events
    if payload is not None:
        payload_bytes = json.dumps(payload, default=str).encode()
        if len(payload_bytes) > _MAX_PAYLOAD_BYTES:
            payload = {
                "_truncated": True,
                "_original_size_bytes": len(payload_bytes),
                "eval_id": payload.get("eval_id"),
            }
            logger.warning(
                "Audit event payload truncated (%d bytes > %d limit)",
                len(payload_bytes),
                _MAX_PAYLOAD_BYTES,
            )

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


def _event_to_export_dict(event: AuditEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "org_id": str(event.org_id),
        "sequence_num": event.sequence_num,
        "event_type": event.event_type,
        "agent_id": event.agent_id,
        "action": event.action,
        "resource": event.resource,
        "decision": event.decision,
        "policy_id": str(event.policy_id) if event.policy_id else None,
        "approval_id": str(event.approval_id) if event.approval_id else None,
        "payload": event.payload,
        "prev_hash": event.prev_hash,
        "entry_hash": event.entry_hash,
        "recorded_at": event.recorded_at.isoformat(),
    }


def _apply_stream_filters(
    stmt: Select[tuple[AuditEvent]],
    org_id: UUID,
    filters: object,
) -> Select[tuple[AuditEvent]]:
    stmt = stmt.where(AuditEvent.org_id == org_id)
    for attr, column in (
        ("event_type", AuditEvent.event_type),
        ("agent_id", AuditEvent.agent_id),
        ("action", AuditEvent.action),
        ("resource", AuditEvent.resource),
        ("decision", AuditEvent.decision),
        ("policy_id", AuditEvent.policy_id),
    ):
        value = getattr(filters, attr, None)
        if value is not None:
            stmt = stmt.where(column == value)

    start_date = getattr(filters, "start_date", None)
    end_date = getattr(filters, "end_date", None)
    if start_date is not None:
        stmt = stmt.where(AuditEvent.recorded_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(AuditEvent.recorded_at <= end_date)
    return stmt


async def stream_audit_events(
    session: AsyncSession,
    org_id: UUID,
    filters: object,
    format: str,
) -> AsyncGenerator[bytes, None]:
    stmt = _apply_stream_filters(select(AuditEvent), org_id, filters).order_by(
        AuditEvent.sequence_num.asc()
    )
    stmt = stmt.execution_options(stream_results=True, yield_per=_STREAM_BATCH_SIZE)
    result = await session.stream(stmt)

    if format == "json":
        first = True
        yield b"["
        async for event in result.scalars():
            if not first:
                yield b","
            yield json.dumps(_event_to_export_dict(event), default=str).encode("utf-8")
            first = False
        yield b"]"
        return

    header_buffer = io.StringIO()
    writer = csv.DictWriter(
        header_buffer,
        fieldnames=[
            "id",
            "org_id",
            "sequence_num",
            "event_type",
            "agent_id",
            "action",
            "resource",
            "decision",
            "policy_id",
            "approval_id",
            "recorded_at",
        ],
    )
    writer.writeheader()
    yield header_buffer.getvalue().encode("utf-8")

    async for event in result.scalars():
        row = _event_to_export_dict(event)
        row_buffer = io.StringIO()
        row_writer = csv.DictWriter(row_buffer, fieldnames=writer.fieldnames or [])
        row_writer.writerow(
            {
                "id": row["id"],
                "org_id": row["org_id"],
                "sequence_num": row["sequence_num"],
                "event_type": row["event_type"],
                "agent_id": row["agent_id"],
                "action": row["action"],
                "resource": row["resource"],
                "decision": row["decision"],
                "policy_id": row["policy_id"] or "",
                "approval_id": row["approval_id"] or "",
                "recorded_at": row["recorded_at"],
            }
        )
        yield row_buffer.getvalue().encode("utf-8")


async def _run_export_job(
    job_id: str,
    org_id: UUID,
    filters: dict[str, object],
    format: str,
) -> None:
    """Stream events to disk and update the DB row on completion/failure.

    Job state is persisted via ``audit_export_jobs`` (W3.5) so the operator can
    resume incomplete exports after a process restart.
    """
    fd, path = tempfile.mkstemp(prefix=f"agr_audit_{job_id}_", suffix=f".{format}")
    os.close(fd)

    try:
        async with async_session_factory() as session:
            with open(path, "wb") as handle:
                filter_obj = type("AuditExportFilters", (), filters)()
                async for chunk in stream_audit_events(session, org_id, filter_obj, format):
                    handle.write(chunk)

        async with async_session_factory() as session:
            record = await session.get(AuditExportJobRecord, UUID(job_id))
            if record is not None:
                record.status = "ready"
                record.file_path = path
                record.finished_at = datetime.now(UTC)
                await session.commit()
    except Exception as exc:
        if os.path.exists(path):
            with contextlib.suppress(OSError):
                os.unlink(path)
        async with async_session_factory() as session:
            record = await session.get(AuditExportJobRecord, UUID(job_id))
            if record is not None:
                record.status = "failed"
                record.error = str(exc)
                record.finished_at = datetime.now(UTC)
                await session.commit()
        logger.exception("Audit export job %s failed", job_id)


async def start_audit_export_job(
    org_id: UUID, filters: dict[str, object], format: str
) -> AuditExportJob:
    """Create a durable export-job row and schedule the background run."""
    job_id = uuid.uuid4()
    async with async_session_factory() as session:
        record = AuditExportJobRecord(
            id=job_id,
            org_id=org_id,
            status="pending",
            format=format,
            filters=filters,
        )
        session.add(record)
        await session.commit()

    asyncio.create_task(_run_export_job(str(job_id), org_id, filters, format))
    return AuditExportJob(job_id=str(job_id), format=format, status="pending")


async def get_audit_export_job(job_id: str, org_id: UUID) -> AuditExportJob | None:
    try:
        job_uuid = UUID(job_id)
    except ValueError:
        return None
    async with async_session_factory() as session:
        record = await session.get(AuditExportJobRecord, job_uuid)
        if record is None or record.org_id != org_id:
            return None
        return _record_to_job(record)


async def resume_pending_audit_exports() -> int:
    """W3.5 — re-schedule pending export jobs that were interrupted by a restart.

    Returns the number of jobs resumed. Safe to call multiple times.
    """
    resumed = 0
    async with async_session_factory() as session:
        result = await session.execute(
            select(AuditExportJobRecord).where(AuditExportJobRecord.status == "pending")
        )
        for record in result.scalars():
            asyncio.create_task(
                _run_export_job(
                    str(record.id),
                    record.org_id,
                    dict(record.filters or {}),
                    record.format,
                )
            )
            resumed += 1
    if resumed:
        logger.info("Resumed %d pending audit export job(s) after restart.", resumed)
    return resumed
