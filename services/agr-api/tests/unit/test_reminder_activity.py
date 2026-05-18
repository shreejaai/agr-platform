"""Unit tests for the send_approval_reminder Temporal activity.

These exercise the inner ``_dispatch_reminder`` helper directly so the
tests don't need a live Temporal cluster — the activity wrapper itself is
a thin session-open / commit shell on top of this helper.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from app.models import ApprovalRequest
from app.workers import activities as activities_module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_pending_approval(
    db_session: AsyncSession, test_org, *, sla_hours: int = 24
) -> ApprovalRequest:
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        org_id=test_org.id,
        agent_id="agent-1",
        action="transfer_funds",
        resource="account:42",
        status="pending",
        approver_email="alice@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=sla_hours),
        sla_hours=sla_hours,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    """Stub out RLS + outbound notifications for every test in this module."""
    monkeypatch.setattr(activities_module, "set_session_rls", AsyncMock())
    monkeypatch.setattr(activities_module, "send_approval_email", AsyncMock())
    monkeypatch.setattr(activities_module, "send_approval_slack", AsyncMock())


@pytest.mark.asyncio
async def test_reminder_dispatch_happy_path(db_session: AsyncSession, test_org) -> None:
    approval = await _make_pending_approval(db_session, test_org)

    result = await activities_module._dispatch_reminder(db_session, str(approval.id))
    await db_session.commit()

    assert result["status"] == "sent"
    activities_module.send_approval_email.assert_awaited_once()
    assert activities_module.send_approval_email.await_args.kwargs == {"is_reminder": True}
    activities_module.send_approval_slack.assert_awaited_once()

    refreshed = (
        await db_session.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval.id))
    ).scalar_one()
    assert refreshed.reminder_sent_at is not None


@pytest.mark.asyncio
async def test_reminder_is_idempotent_once_sent(db_session: AsyncSession, test_org) -> None:
    approval = await _make_pending_approval(db_session, test_org)
    approval.reminder_sent_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()

    result = await activities_module._dispatch_reminder(db_session, str(approval.id))

    assert result["status"] == "already_sent"
    activities_module.send_approval_email.assert_not_awaited()
    activities_module.send_approval_slack.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_skips_non_pending_approval(db_session: AsyncSession, test_org) -> None:
    approval = await _make_pending_approval(db_session, test_org)
    approval.status = "approved"
    await db_session.commit()

    result = await activities_module._dispatch_reminder(db_session, str(approval.id))

    assert result["status"] == "not_pending"
    activities_module.send_approval_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_missing_approval_returns_status(db_session: AsyncSession) -> None:
    result = await activities_module._dispatch_reminder(db_session, str(uuid.uuid4()))
    assert result["status"] == "missing"


@pytest.mark.asyncio
async def test_reminder_rejects_invalid_id(db_session: AsyncSession) -> None:
    result = await activities_module._dispatch_reminder(db_session, "not-a-uuid")
    assert result["status"] == "invalid_id"
