import uuid
from unittest.mock import AsyncMock

import pytest
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
