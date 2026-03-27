"""CrewAI plugin — AGRToolWrapper class decorator."""

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from agr.client import AGRClient
from agr.integrations.frameworks import AGRPolicyEnforcer

P = ParamSpec("P")
R = TypeVar("R")


def AGRToolWrapper(
    client: AGRClient,
    agent_id: str,
    resource: str | None = None,
) -> Callable[[type], type]:
    """Class decorator that wraps CrewAI BaseTool._run with AGR governance."""
    enforcer = AGRPolicyEnforcer(client, agent_id)

    def decorator(cls: type) -> type:
        original_run = cls._run  # type: ignore[attr-defined]

        @functools.wraps(original_run)
        def governed_run(self: object, *args: object, **kwargs: object) -> object:
            tool_name = getattr(cls, "name", cls.__name__)
            enforcer.before_tool(
                action=str(tool_name),
                resource=resource or str(tool_name),
            )
            return original_run(self, *args, **kwargs)

        cls._run = governed_run  # type: ignore[attr-defined]
        return cls

    return decorator
