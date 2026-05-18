import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from app.config import settings
from app.services.approval_service import create_approval_request
from app.services.temporal_service import WorkflowStartResult
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_approval_request_returns_db_only_mode(
    db_session: AsyncSession, test_org
) -> None:
    temporal_mock = AsyncMock(
        return_value=WorkflowStartResult(
            workflow_id=None,
            fallback_mode="db_only_temporal_unavailable",
            error="temporal_unavailable",
        )
    )
    slack_mock = AsyncMock()

    from app.services import approval_service as approval_module
    from app.services import slack_service as slack_module

    original_temporal = approval_module.start_approval_workflow
    original_slack = slack_module.send_approval_slack
    approval_module.start_approval_workflow = temporal_mock
    slack_module.send_approval_slack = slack_mock
    try:
        approval = await create_approval_request(
            session=db_session,
            org_id=test_org.id,
            agent_id="agent-1",
            action="deploy",
            resource="prod",
        )
    finally:
        approval_module.start_approval_workflow = original_temporal
        slack_module.send_approval_slack = original_slack

    assert approval.workflow_mode == "db_only"
    assert approval.temporal_run_id is None


@pytest.mark.asyncio
async def test_create_approval_request_returns_temporal_mode(
    db_session: AsyncSession, test_org
) -> None:
    temporal_mock = AsyncMock(
        return_value=WorkflowStartResult(
            workflow_id=f"approval-{uuid.uuid4()}",
            fallback_mode="none",
            error=None,
        )
    )
    slack_mock = AsyncMock()

    from app.services import approval_service as approval_module
    from app.services import slack_service as slack_module

    original_temporal = approval_module.start_approval_workflow
    original_slack = slack_module.send_approval_slack
    approval_module.start_approval_workflow = temporal_mock
    slack_module.send_approval_slack = slack_mock
    try:
        approval = await create_approval_request(
            session=db_session,
            org_id=test_org.id,
            agent_id="agent-1",
            action="deploy",
            resource="prod",
        )
    finally:
        approval_module.start_approval_workflow = original_temporal
        slack_module.send_approval_slack = original_slack

    assert approval.workflow_mode == "temporal"
    assert approval.temporal_run_id is not None


# ── W2.2: sla_hours honored on creation ──────────────────────────────────────


async def _create_with_sla(db_session: AsyncSession, test_org, sla_hours: int | None):
    """Helper: build an approval with `sla_hours` mocking temporal+slack."""
    from app.services import approval_service as approval_module
    from app.services import slack_service as slack_module

    temporal_mock = AsyncMock(
        return_value=WorkflowStartResult(
            workflow_id=None,
            fallback_mode="db_only_temporal_unavailable",
            error="temporal_unavailable",
        )
    )
    slack_mock = AsyncMock()
    original_temporal = approval_module.start_approval_workflow
    original_slack = slack_module.send_approval_slack
    approval_module.start_approval_workflow = temporal_mock
    slack_module.send_approval_slack = slack_mock
    try:
        before = datetime.now(UTC)
        approval = await create_approval_request(
            session=db_session,
            org_id=test_org.id,
            agent_id="agent-1",
            action="deploy",
            resource="prod",
            sla_hours=sla_hours,
        )
        return approval, before, temporal_mock
    finally:
        approval_module.start_approval_workflow = original_temporal
        slack_module.send_approval_slack = original_slack


@pytest.mark.asyncio
@pytest.mark.parametrize("sla", [1, 24, 72])
async def test_sla_hours_drives_expires_at(db_session: AsyncSession, test_org, sla: int) -> None:
    approval, before, temporal_mock = await _create_with_sla(db_session, test_org, sla)

    delta_hours = (approval.expires_at - before).total_seconds() / 3600.0
    # Allow ±1 minute of clock drift between `before` and the row's `expires_at`.
    assert abs(delta_hours - sla) < (
        1 / 60.0
    ), f"expected expires_at ~= now + {sla}h, got {delta_hours:.4f}h"
    assert approval.sla_hours == sla
    # Workflow start receives the same SLA so DB-row + workflow agree.
    temporal_mock.assert_awaited_once()
    assert temporal_mock.await_args.kwargs.get("sla_hours") == sla


@pytest.mark.asyncio
async def test_sla_hours_defaults_to_settings(db_session: AsyncSession, test_org) -> None:
    approval, before, _ = await _create_with_sla(db_session, test_org, None)

    expected = settings.default_sla_hours
    delta_hours = (approval.expires_at - before).total_seconds() / 3600.0
    assert abs(delta_hours - expected) < (1 / 60.0)
    assert approval.sla_hours == expected


@pytest.mark.asyncio
async def test_sla_hours_caps_at_max(db_session: AsyncSession, test_org) -> None:
    too_long = settings.max_sla_hours + 500
    approval, _, _ = await _create_with_sla(db_session, test_org, too_long)
    assert approval.sla_hours == settings.max_sla_hours


@pytest.mark.asyncio
async def test_sla_hours_invalid_falls_back_to_default(db_session: AsyncSession, test_org) -> None:
    # Zero / negative SLA should not produce an already-expired approval.
    approval, _, _ = await _create_with_sla(db_session, test_org, 0)
    assert approval.sla_hours == settings.default_sla_hours
