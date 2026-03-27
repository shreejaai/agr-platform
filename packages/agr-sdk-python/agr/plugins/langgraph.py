"""LangGraph plugin — @agr_governed decorator for LangGraph tools."""

from collections.abc import Callable
from typing import ParamSpec, TypeVar

from agr.client import AGRClient
from agr.integrations.frameworks import AGRPolicyEnforcer

P = ParamSpec("P")
R = TypeVar("R")


def agr_governed(
    client: AGRClient,
    agent_id: str,
    resource: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that evaluates AGR policies before every tool call.

    - ALLOW: tool executes normally
    - DENY: raises AGRError
    - APPROVAL_REQUIRED: blocks until approved, then executes
    """

    enforcer = AGRPolicyEnforcer(client, agent_id)

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        return enforcer.wrap(func, action=func.__name__, resource=resource)

    return decorator
