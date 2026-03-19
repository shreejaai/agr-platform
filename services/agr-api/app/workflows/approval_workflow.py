"""Temporal workflow — durable approval suspension.

ApprovalWorkflow suspends for up to 48 hours waiting for a human_decision signal.
If no signal arrives, the workflow times out and returns "expired".

Run the worker process to activate this workflow:
    python -m app.workers.approval_worker
"""

from datetime import timedelta

from temporalio import workflow


@workflow.defn
class ApprovalWorkflow:
    """Durable approval gate — holds an agent action pending human review."""

    def __init__(self) -> None:
        self._decision: str | None = None

    @workflow.run
    async def run(self, approval_id: str) -> str:
        """Suspend until a human_decision signal arrives or the 48h window expires.

        Returns the decision string: "approved" | "rejected" | "expired"
        """
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(hours=48),
            )
        except TimeoutError:
            return "expired"

        return self._decision or "expired"

    @workflow.signal
    def human_decision(self, decision: str) -> None:
        """Receive the human decision and unblock the workflow."""
        self._decision = decision
