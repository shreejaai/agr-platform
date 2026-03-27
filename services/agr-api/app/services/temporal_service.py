"""Temporal integration service.

Provides start_approval_workflow() and signal_approval_workflow().
Both are optional — if TEMPORAL_HOST is not configured or Temporal is
unreachable, they log a warning and return gracefully. The approval flow
continues with DB-only tracking.

A lazily cached client is used to avoid reconnecting on every call.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

TASK_QUEUE = "agr-approvals"
_START_RETRY_ATTEMPTS = 3
_SIGNAL_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5

_temporal_client: object | None = None
_client_initialised = False
_client_connected = False  # True only if connection actually succeeded


@dataclass(slots=True)
class WorkflowStartResult:
    workflow_id: str | None
    fallback_mode: str
    error: str | None = None


@dataclass(slots=True)
class WorkflowSignalResult:
    delivered: bool
    error: str | None = None


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


async def start_approval_workflow(approval_id: UUID) -> WorkflowStartResult:
    """Start a durable ApprovalWorkflow for an approval request.

    Returns:
        The Temporal workflow ID if started, or None if Temporal is unavailable.

    When Temporal is unavailable, the approval is tracked by DB row only.
    This is a graceful degradation — the approval flow still works via email
    token links and API polling, but lacks durable retry/timeout/reminder
    semantics. Ops should monitor for TEMPORAL_UNAVAILABLE log entries.
    """
    client = await _get_client()
    if client is None:
        logger.warning(
            "Temporal unavailable — approval %s will be tracked by DB row only. "
            "mode=db_only approval_id=%s "
            "Set TEMPORAL_HOST to enable durable approval workflows.",
            approval_id,
            approval_id,
        )
        return WorkflowStartResult(
            workflow_id=None,
            fallback_mode="db_only_temporal_unavailable",
            error="temporal_unavailable",
        )

    last_error: str | None = None
    for attempt in range(1, _START_RETRY_ATTEMPTS + 1):
        try:
            from temporalio.client import Client
            from temporalio.common import RetryPolicy

            from app.workflows.approval_workflow import ApprovalWorkflow

            assert isinstance(client, Client)
            workflow_id = f"approval-{approval_id}"
            handle = await client.start_workflow(
                ApprovalWorkflow.run,
                str(approval_id),
                id=workflow_id,
                task_queue=TASK_QUEUE,
                execution_timeout=timedelta(hours=50),
                run_timeout=timedelta(hours=50),
                task_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=15),
                    maximum_attempts=3,
                ),
            )
            logger.info("Started Temporal workflow %s for approval %s", handle.id, approval_id)
            return WorkflowStartResult(workflow_id=handle.id, fallback_mode="none")
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Failed to start Temporal workflow for approval %s (attempt %d/%d): %s",
                approval_id,
                attempt,
                _START_RETRY_ATTEMPTS,
                exc,
            )
            if attempt < _START_RETRY_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    return WorkflowStartResult(
        workflow_id=None,
        fallback_mode="db_only_start_failed",
        error=last_error or "workflow_start_failed",
    )


async def _signal_workflow(
    workflow_id: str,
    *,
    signal_name: str,
    payload: str,
) -> WorkflowSignalResult:
    """Send a human_decision signal to a running ApprovalWorkflow.

    Args:
        workflow_id: The Temporal workflow ID stored in temporal_run_id.
        decision:    "approved" or "rejected".

    Returns:
        WorkflowSignalResult describing signal delivery.
    """
    client = await _get_client()
    if client is None:
        return WorkflowSignalResult(delivered=False, error="temporal_unavailable")

    last_error: str | None = None
    for attempt in range(1, _SIGNAL_RETRY_ATTEMPTS + 1):
        try:
            from temporalio.client import Client

            from app.workflows.approval_workflow import ApprovalWorkflow

            assert isinstance(client, Client)
            handle = client.get_workflow_handle(workflow_id)
            if signal_name == "human_decision":
                await handle.signal(ApprovalWorkflow.human_decision, payload)
            else:
                await handle.signal(ApprovalWorkflow.escalate, payload)
            logger.info("Signaled workflow %s with %s=%s", workflow_id, signal_name, payload)
            return WorkflowSignalResult(delivered=True)
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Failed to signal workflow %s with %s (attempt %d/%d): %s",
                workflow_id,
                signal_name,
                attempt,
                _SIGNAL_RETRY_ATTEMPTS,
                exc,
            )
            if attempt < _SIGNAL_RETRY_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    return WorkflowSignalResult(delivered=False, error=last_error or "signal_failed")


async def signal_approval_workflow(workflow_id: str, decision: str) -> WorkflowSignalResult:
    return await _signal_workflow(workflow_id, signal_name="human_decision", payload=decision)


async def signal_approval_escalation(workflow_id: str, approver_email: str) -> WorkflowSignalResult:
    return await _signal_workflow(workflow_id, signal_name="escalate", payload=approver_email)
