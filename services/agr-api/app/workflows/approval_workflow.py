"""Temporal workflow — durable approval suspension.

ApprovalWorkflow suspends for up to 48 hours waiting for a human_decision signal.
If no signal arrives within the configured timeout, the workflow returns "expired".

Reminder behaviour:
  - 24 hours after creation, if still pending, a reminder signal is logged.
    Callers that need email reminders should hook into the human_decision signal
    or implement a separate activity.

Run the worker process to activate this workflow:
    python -m app.workers.approval_worker
"""

from datetime import timedelta

from temporalio import workflow

# ── Default timeouts ──────────────────────────────────────────────────────────
_APPROVAL_TIMEOUT_HOURS = 48
_REMINDER_AFTER_HOURS = 24


@workflow.defn
class ApprovalWorkflow:
    """Durable approval gate — holds an agent action pending human review."""

    def __init__(self) -> None:
        self._decision: str | None = None
        self._reminder_sent: bool = False

    @workflow.run
    async def run(self, approval_id: str) -> str:
        """Suspend until a human_decision signal arrives or the 48h window expires.

        Emits a reminder log at 24h if no decision has been received.
        Returns: "approved" | "rejected" | "expired"
        """
        reminder_timeout = timedelta(hours=_REMINDER_AFTER_HOURS)

        # Phase 1 — wait up to reminder threshold
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=reminder_timeout,
            )
        except TimeoutError:
            # No decision received by reminder point — log it
            if not self._reminder_sent:
                workflow.logger.warning(
                    "Approval %s has been pending for %dh with no decision. "
                    "Consider escalating or extending the timeout.",
                    approval_id,
                    _REMINDER_AFTER_HOURS,
                )
                self._reminder_sent = True

        if self._decision is not None:
            return self._decision

        # Phase 2 — wait for remaining window
        remaining = timedelta(hours=_APPROVAL_TIMEOUT_HOURS - _REMINDER_AFTER_HOURS)
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=remaining,
            )
        except TimeoutError:
            workflow.logger.warning(
                "Approval %s expired after %dh with no decision.",
                approval_id,
                _APPROVAL_TIMEOUT_HOURS,
            )
            return "expired"

        return self._decision or "expired"

    @workflow.signal
    def human_decision(self, decision: str) -> None:
        """Receive the human decision and unblock the workflow."""
        self._decision = decision

    @workflow.query
    def is_pending(self) -> bool:
        """Query whether the workflow is still waiting for a decision."""
        return self._decision is None
