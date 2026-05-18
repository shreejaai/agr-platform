"""W3.5 — durable audit export jobs survive process restarts."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import AuditExportJobRecord, Organization
from app.services import audit_service
from sqlalchemy import select

from tests.conftest import test_session_factory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def patched_audit_factory(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(audit_service, "async_session_factory", test_session_factory)
    yield


@pytest_asyncio.fixture
async def export_org(db_session: AsyncSession) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="W3.5 export org",
        slug=f"w35-{uuid.uuid4().hex[:8]}",
        plan="developer",
        api_key=f"agr_sk_{uuid.uuid4().hex}",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest.mark.asyncio
async def test_start_audit_export_job_persists_row(
    patched_audit_factory: None,
    export_org: Organization,
) -> None:
    job = await audit_service.start_audit_export_job(export_org.id, {}, "json")
    for _ in range(40):
        fetched = await audit_service.get_audit_export_job(job.job_id, export_org.id)
        assert fetched is not None
        if fetched.status in {"ready", "failed"}:
            break
        await asyncio.sleep(0.05)

    fetched = await audit_service.get_audit_export_job(job.job_id, export_org.id)
    assert fetched is not None
    assert fetched.status == "ready"
    assert fetched.file_path is not None

    other = uuid.uuid4()
    assert await audit_service.get_audit_export_job(job.job_id, other) is None


@pytest.mark.asyncio
async def test_resume_pending_audit_exports_reschedules_orphans(
    patched_audit_factory: None,
    export_org: Organization,
) -> None:
    job_id = uuid.uuid4()
    async with test_session_factory() as session:
        session.add(
            AuditExportJobRecord(
                id=job_id,
                org_id=export_org.id,
                status="pending",
                format="json",
                filters={},
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()

    resumed = await audit_service.resume_pending_audit_exports()
    assert resumed >= 1

    for _ in range(40):
        fetched = await audit_service.get_audit_export_job(str(job_id), export_org.id)
        assert fetched is not None
        if fetched.status != "pending":
            break
        await asyncio.sleep(0.05)

    async with test_session_factory() as session:
        result = await session.execute(
            select(AuditExportJobRecord).where(AuditExportJobRecord.id == job_id)
        )
        record = result.scalar_one()
        assert record.status in {"ready", "failed"}
        assert record.finished_at is not None
