"""LangGraph plugin — @agr_governed decorator for LangGraph tools."""

import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from agr.client import AGRClient, AGRError

logger = logging.getLogger(__name__)

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

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            action = func.__name__
            target = resource or action

            result = client.evaluate(
                agent=agent_id,
                action=action,
                resource=target,
            )

            if result.denied:
                raise AGRError(f"Action '{action}' denied by AGR policy: {result.reason}")

            if result.requires_approval and result.approval_id:
                logger.info(
                    "Action '%s' requires approval (id=%s). Waiting...",
                    action,
                    result.approval_id,
                )
                approved = client.wait_for_approval(result.approval_id)
                if not approved:
                    raise AGRError(f"Action '{action}' was rejected during approval.")

            return func(*args, **kwargs)

        return wrapper

    return decorator
