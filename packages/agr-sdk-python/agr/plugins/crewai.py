"""CrewAI plugin — AGRToolWrapper class decorator."""

import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from agr.client import AGRClient, AGRError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def AGRToolWrapper(
    client: AGRClient,
    agent_id: str,
    resource: str | None = None,
) -> Callable[[type], type]:
    """Class decorator that wraps CrewAI BaseTool._run with AGR governance."""

    def decorator(cls: type) -> type:
        original_run = cls._run  # type: ignore[attr-defined]

        @functools.wraps(original_run)
        def governed_run(self: object, *args: object, **kwargs: object) -> object:
            tool_name = getattr(cls, "name", cls.__name__)
            target = resource or str(tool_name)

            result = client.evaluate(
                agent=agent_id,
                action=str(tool_name),
                resource=target,
            )

            if result.denied:
                raise AGRError(f"Action '{tool_name}' denied by AGR policy: {result.reason}")

            if result.requires_approval and result.approval_id:
                logger.info(
                    "Action '%s' requires approval (id=%s). Waiting...",
                    tool_name,
                    result.approval_id,
                )
                approved = client.wait_for_approval(result.approval_id)
                if not approved:
                    raise AGRError(f"Action '{tool_name}' was rejected during approval.")

            return original_run(self, *args, **kwargs)

        cls._run = governed_run  # type: ignore[attr-defined]
        return cls

    return decorator
