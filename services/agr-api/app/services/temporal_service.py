"""Temporal integration service.

Provides start_approval_workflow() and signal_approval_workflow().
Both are optional — if TEMPORAL_HOST is not configured or Temporal is
unreachable, they log a warning and return gracefully. The approval flow
continues with DB-only tracking.

A lazily cached client is used to avoid reconnecting on every call.
"""

import logging
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

TASK_QUEUE = "agr-approvals"

_temporal_client: object | None = None
_client_initialised = False
_client_connected = False  # True only if connection actually succeeded


async def _get_client() -> object | None:
    """Return a lazily initialised Temporal client, or None if unavailable.

    L5: if the initial connection failed (_client_connected=False), we retry
    on the next call instead of caching the failure permanently. This allows
    the app to reconnect after a Temporal restart without a process restart.
    """
    global _temporal_client, _client_initialised, _client_connected
    if _client_initialised and _client_connected:
        return _temporal_client
    # Either first call or previous attempt failed — try to connect
    _client_initialised = True
    if not settings.temporal_host:
        return None

    try:
        from temporalio.client import Client

        _temporal_client = await Client.connect(
            settings.temporal_host, namespace=settings.temporal_namespace
        )
        _client_connected = True
        logger.info("Connected to Temporal at %s", settings.temporal_host)
    except Exception as exc:
        logger.warning("Could not connect to Temporal (%s): %s", settings.temporal_host, exc)
        _temporal_client = None
        _client_connected = False
        # Reset so the next call retries (allows reconnect after Temporal restart)
        _client_initialised = False

    return _temporal_client


async def start_approval_workflow(approval_id: UUID) -> str | None:
    """Start a durable ApprovalWorkflow for an approval request.

    Returns:
        The Temporal workflow ID if started, or None if Temporal is unavailable.
    """
    client = await _get_client()
    if client is None:
        return None

    try:
        from temporalio.client import Client

        from app.workflows.approval_workflow import ApprovalWorkflow

        assert isinstance(client, Client)
        workflow_id = f"approval-{approval_id}"
        handle = await client.start_workflow(
            ApprovalWorkflow.run,
            str(approval_id),
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
        logger.info("Started Temporal workflow %s for approval %s", handle.id, approval_id)
        return handle.id
    except Exception as exc:
        logger.warning("Failed to start Temporal workflow for approval %s: %s", approval_id, exc)
        return None


async def signal_approval_workflow(workflow_id: str, decision: str) -> bool:
    """Send a human_decision signal to a running ApprovalWorkflow.

    Args:
        workflow_id: The Temporal workflow ID stored in temporal_run_id.
        decision:    "approved" or "rejected".

    Returns:
        True if the signal was delivered, False otherwise.
    """
    client = await _get_client()
    if client is None:
        return False

    try:
        from temporalio.client import Client

        from app.workflows.approval_workflow import ApprovalWorkflow

        assert isinstance(client, Client)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(ApprovalWorkflow.human_decision, decision)
        logger.info("Signaled workflow %s with decision=%s", workflow_id, decision)
        return True
    except Exception as exc:
        logger.warning("Failed to signal workflow %s: %s", workflow_id, exc)
        return False
