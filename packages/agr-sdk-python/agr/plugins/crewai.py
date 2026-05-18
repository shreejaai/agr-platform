"""CrewAI plugin — AGRToolWrapper class decorator."""

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from agr.client import AGRClient, PendingApprovalResult
from agr.integrations.frameworks import AGRPolicyEnforcer, ApprovalMode

P = ParamSpec("P")
R = TypeVar("R")


def AGRToolWrapper(
    client: AGRClient,
    agent_id: str,
    resource: str | None = None,
    *,
    mode: ApprovalMode = "block",
) -> Callable[[type], type]:
    """Class decorator that wraps CrewAI ``BaseTool._run`` with AGR governance.

    In ``mode='non_blocking'`` the wrapped ``_run`` returns a
    :class:`PendingApprovalResult` when AGR requires human review, instead
    of blocking the crew worker. The CrewAI orchestrator can route that
    return value through its own retry / hand-off logic.
    """
    enforcer = AGRPolicyEnforcer(client, agent_id)

    def decorator(cls: type) -> type:
        original_run = cls._run  # type: ignore[attr-defined]

        @functools.wraps(original_run)
        def governed_run(self: object, *args: object, **kwargs: object) -> object:
            tool_name = getattr(cls, "name", cls.__name__)
            outcome = enforcer.before_tool(
                action=str(tool_name),
                resource=resource or str(tool_name),
                mode=mode,
            )
            if isinstance(outcome, PendingApprovalResult):
                return outcome
            return original_run(self, *args, **kwargs)

        cls._run = governed_run  # type: ignore[attr-defined]
        return cls

    return decorator
