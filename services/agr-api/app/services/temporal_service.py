"""Temporal integration service.

Provides start_approval_workflow() and signal_approval_workflow().
Both are optional — if TEMPORAL_HOST is not configured or Temporal is
unreachable, they log a warning and return gracefully. The approval flow
continues with DB-only tracking.

A lazily cached client is used to avoid reconnecting on every call.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

TASK_QUEUE = "agr-approvals"
_START_RETRY_ATTEMPTS = 3
_SIGNAL_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5

# ── W3.2 circuit breaker ──────────────────────────────────────────────────────
# closed   → normal operation
# open     → short-circuit all calls; bypass Temporal entirely
# half_open→ allow exactly one probe call to check recovery
_CB_FAILURE_THRESHOLD = 5
_CB_FAILURE_WINDOW_SEC = 30.0
_CB_OPEN_DURATION_SEC = 30.0


class _CircuitBreaker:
    __slots__ = ("state", "failures", "opened_at", "half_open_in_flight", "_lock")

    def __init__(self) -> None:
        self.state: str = "closed"
        self.failures: list[float] = []
        self.opened_at: float = 0.0
        self.half_open_in_flight: bool = False
        self._lock = asyncio.Lock()

    async def allow_request(self) -> bool:
        """Return True if the call should be attempted, False if short-circuited."""
        async with self._lock:
            now = time.monotonic()
            if self.state == "open":
                if now - self.opened_at >= _CB_OPEN_DURATION_SEC:
                    self.state = "half_open"
                    self.half_open_in_flight = False
                    _emit_state("half_open")
                else:
                    return False
            if self.state == "half_open":
                if self.half_open_in_flight:
                    return False
                self.half_open_in_flight = True
                return True
            return True  # closed

    async def record_success(self) -> None:
        async with self._lock:
            self.failures.clear()
            if self.state in ("open", "half_open"):
                self.state = "closed"
                self.half_open_in_flight = False
                _emit_state("closed")
            elif self.state == "closed":
                _emit_state("closed")

    async def record_failure(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self.state == "half_open":
                self.state = "open"
                self.opened_at = now
                self.half_open_in_flight = False
                self.failures.clear()
                _emit_state("open")
                _emit_trip()
                return
            self.failures = [t for t in self.failures if now - t <= _CB_FAILURE_WINDOW_SEC]
            self.failures.append(now)
            if len(self.failures) >= _CB_FAILURE_THRESHOLD and self.state == "closed":
                self.state = "open"
                self.opened_at = now
                self.failures.clear()
                _emit_state("open")
                _emit_trip()

    def snapshot(self) -> str:
        return self.state


def _emit_state(state: str) -> None:
    try:
        from app.services.metrics_service import set_temporal_circuit_state

        set_temporal_circuit_state(state)
    except Exception:
        pass


def _emit_trip() -> None:
    try:
        from app.services.metrics_service import record_temporal_circuit_trip

        record_temporal_circuit_trip()
    except Exception:
        pass


_circuit = _CircuitBreaker()


def get_circuit_state() -> str:
    return _circuit.snapshot()


def _reset_circuit_for_tests() -> None:
    """Test helper — fully reset breaker state."""
    _circuit.state = "closed"
    _circuit.failures.clear()
    _circuit.opened_at = 0.0
    _circuit.half_open_in_flight = False
    _emit_state("closed")


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


def _record_fallback(mode: str) -> str:
    """Increment the approval-workflow-fallback Prometheus counter (best-effort)."""
    try:
        from app.services.metrics_service import record_approval_workflow_fallback

        record_approval_workflow_fallback(mode)
    except Exception:
        pass
    return mode


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


async def start_approval_workflow(
    approval_id: UUID,
    *,
    sla_hours: int | None = None,
) -> WorkflowStartResult:
    """Start a durable ApprovalWorkflow for an approval request.

    Returns:
        The Temporal workflow ID if started, or None if Temporal is unavailable.

    When Temporal is unavailable, the approval is tracked by DB row only.
    This is a graceful degradation — the approval flow still works via email
    token links and API polling, but lacks durable retry/timeout/reminder
    semantics. Ops should monitor for TEMPORAL_UNAVAILABLE log entries.

    sla_hours, when provided, is forwarded to the workflow so the suspension
    window matches the DB-row expiry. When unset the workflow uses its
    built-in default (48h).
    """
    if not await _circuit.allow_request():
        logger.warning(
            "Temporal circuit OPEN — short-circuiting start_approval_workflow for %s",
            approval_id,
        )
        return WorkflowStartResult(
            workflow_id=None,
            fallback_mode=_record_fallback("db_only_circuit_open"),
            error="temporal_circuit_open",
        )
    client = await _get_client()
    if client is None:
        await _circuit.record_failure()
        logger.warning(
            "Temporal unavailable — approval %s will be tracked by DB row only. "
            "mode=db_only approval_id=%s "
            "Set TEMPORAL_HOST to enable durable approval workflows.",
            approval_id,
            approval_id,
        )
        return WorkflowStartResult(
            workflow_id=None,
            fallback_mode=_record_fallback("db_only_temporal_unavailable"),
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
            # Add a small buffer so the workflow's own SLA-driven wait_condition
            # always fires before Temporal kills the run for exceeding its timeout.
            execution_window_hours = (sla_hours or 48) + 2
            handle = await client.start_workflow(
                ApprovalWorkflow.run,
                args=[str(approval_id), sla_hours],
                id=workflow_id,
                task_queue=TASK_QUEUE,
                execution_timeout=timedelta(hours=execution_window_hours),
                run_timeout=timedelta(hours=execution_window_hours),
                task_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=15),
                    maximum_attempts=3,
                ),
            )
            logger.info("Started Temporal workflow %s for approval %s", handle.id, approval_id)
            await _circuit.record_success()
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

    await _circuit.record_failure()
    return WorkflowStartResult(
        workflow_id=None,
        fallback_mode=_record_fallback("db_only_start_failed"),
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
    if not await _circuit.allow_request():
        return WorkflowSignalResult(delivered=False, error="temporal_circuit_open")
    client = await _get_client()
    if client is None:
        await _circuit.record_failure()
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
            await _circuit.record_success()
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

    await _circuit.record_failure()
    return WorkflowSignalResult(delivered=False, error=last_error or "signal_failed")


async def signal_approval_workflow(workflow_id: str, decision: str) -> WorkflowSignalResult:
    return await _signal_workflow(workflow_id, signal_name="human_decision", payload=decision)


async def signal_approval_escalation(workflow_id: str, approver_email: str) -> WorkflowSignalResult:
    return await _signal_workflow(workflow_id, signal_name="escalate", payload=approver_email)
