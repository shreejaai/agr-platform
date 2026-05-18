"""Temporal workflow — durable approval suspension.

ApprovalWorkflow suspends until a human_decision signal arrives or its SLA
window expires (default 48h, configurable per-approval via sla_hours).
If no signal arrives within the configured timeout, the workflow returns "expired".

Reminder behaviour:
  - Halfway through the SLA window, if still pending, the workflow invokes the
    `send_approval_reminder` activity which sends a follow-up email + Slack and
    writes an APPROVAL_REMINDER_SENT audit event. The activity is idempotent.

Run the worker process to activate this workflow:
    python -m app.workers.approval_worker
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# ── Default SLA when caller does not provide one ──────────────────────────────
_DEFAULT_SLA_HOURS = 48
# Reminder fires at this fraction of the total SLA window.
_REMINDER_FRACTION = 0.5
# Name of the activity registered in app.workers.activities — kept as a string
# so the workflow module never imports activity I/O code (Temporal requirement).
_REMINDER_ACTIVITY = "send_approval_reminder"
_REMINDER_TIMEOUT = timedelta(seconds=60)
_REMINDER_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))


@workflow.defn
class ApprovalWorkflow:
    """Durable approval gate — holds an agent action pending human review."""

    def __init__(self) -> None:
        self._decision: str | None = None
        self._reminder_sent: bool = False
        self._status: str = "running"
        self._escalation_target: str | None = None

    @workflow.run
    async def run(self, approval_id: str, sla_hours: int | None = None) -> str:
        """Suspend until a human_decision signal arrives or the SLA window expires.

        Emits a reminder log halfway through the SLA window if no decision
        has been received. Returns: "approved" | "rejected" | "failed".
        """
        total_hours = sla_hours if sla_hours and sla_hours > 0 else _DEFAULT_SLA_HOURS
        reminder_hours = max(1.0, total_hours * _REMINDER_FRACTION)
        reminder_timeout = timedelta(hours=reminder_hours)

        # Phase 1 — wait up to reminder threshold
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=reminder_timeout,
            )
        except TimeoutError:
            # No decision received by reminder point — dispatch reminder via activity.
            # The activity is idempotent (reminder_sent_at column guard) so workflow
            # replays / retries never produce duplicate notifications.
            if not self._reminder_sent:
                try:
                    await workflow.execute_activity(
                        _REMINDER_ACTIVITY,
                        approval_id,
                        start_to_close_timeout=_REMINDER_TIMEOUT,
                        retry_policy=_REMINDER_RETRY,
                    )
                except Exception as exc:  # noqa: BLE001 — log and continue waiting
                    workflow.logger.warning(
                        "Approval %s reminder activity failed: %s", approval_id, exc
                    )
                self._reminder_sent = True

        if self._decision is not None:
            self._status = "completed"
            return self._decision

        # Phase 2 — wait for remaining window
        remaining = timedelta(hours=total_hours - reminder_hours)
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=remaining,
            )
        except TimeoutError:
            self._status = "failed"
            workflow.logger.warning(
                "Approval %s expired after %dh with no decision.",
                approval_id,
                total_hours,
            )
            return "failed"

        self._status = "completed"
        return self._decision or "failed"

    @workflow.signal
    def human_decision(self, decision: str) -> None:
        """Receive the human decision and unblock the workflow."""
        self._decision = decision
        self._status = "completed"

    @workflow.signal
    def escalate(self, approver_email: str) -> None:
        """Record that the workflow was escalated to a new approver."""
        self._escalation_target = approver_email
        if self._decision is None:
            self._status = "escalated"

    @workflow.query
    def is_pending(self) -> bool:
        """Query whether the workflow is still waiting for a decision."""
        return self._decision is None

    @workflow.query
    def workflow_status(self) -> dict[str, str | None]:
        return {
            "status": self._status,
            "escalation_target": self._escalation_target,
        }
