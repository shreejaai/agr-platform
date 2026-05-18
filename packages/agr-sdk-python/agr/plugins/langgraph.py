"""LangGraph plugin — @agr_governed decorator for LangGraph tools."""

from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

from agr.client import AGRClient, PendingApprovalResult
from agr.integrations.frameworks import AGRPolicyEnforcer, ApprovalMode

P = ParamSpec("P")
R = TypeVar("R")


def agr_governed(
    client: AGRClient,
    agent_id: str,
    resource: str | None = None,
    *,
    mode: ApprovalMode = "block",
) -> Callable[[Callable[P, R]], Callable[P, R | PendingApprovalResult]]:
    """Decorator that evaluates AGR policies before every tool call.

    - ALLOW: tool executes normally
    - DENY: raises AGRError
    - APPROVAL_REQUIRED + ``mode='block'`` (default): blocks until approved
      then runs the tool, raises AGRError on rejection.
    - APPROVAL_REQUIRED + ``mode='non_blocking'``: returns a
      :class:`PendingApprovalResult` immediately so a LangGraph node can
      checkpoint the state and resume after a human acts on the approval.
    """

    enforcer = AGRPolicyEnforcer(client, agent_id)

    def decorator(func: Callable[P, R]) -> Callable[P, R | PendingApprovalResult]:
        return cast(
            "Callable[P, R | PendingApprovalResult]",
            enforcer.wrap(func, action=func.__name__, resource=resource, mode=mode),
        )

    return decorator
