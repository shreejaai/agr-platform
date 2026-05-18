"""LangChain tool wrapper that consults AGR before execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agr.client import AGRClient

try:
    from langchain_core.tools import BaseTool, ToolException
except ImportError:  # pragma: no cover - optional dependency

    class ToolGuardError(Exception):
        pass

    ToolException = ToolGuardError

    class BaseTool:  # type: ignore[no-redef]
        name: str = "tool"
        description: str = ""

        def _run(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def _arun(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError


# Imported eagerly here (not inside TYPE_CHECKING) so isinstance() works at
# runtime in _evaluate when we decide whether to short-circuit.
try:  # pragma: no cover - exercised via integration tests
    from agr.client import PendingApprovalResult as _PendingApprovalResult
except ImportError:  # pragma: no cover - SDK installed separately
    _PendingApprovalResult = None  # type: ignore[assignment,misc]


GuardMode = Literal["non_blocking", "block_until_resolved"]


class AGRToolGuard(BaseTool):
    agr_client: AGRClient
    wrapped_tool: BaseTool
    agent_id: str
    mode: GuardMode

    def __init__(
        self,
        agr_client: AGRClient,
        wrapped_tool: BaseTool,
        agent_id: str,
        *,
        mode: GuardMode = "non_blocking",
        poll_interval: float = 2.0,
        approval_timeout: float = 3600.0,
    ) -> None:
        super().__init__()
        self.agr_client = agr_client
        self.wrapped_tool = wrapped_tool
        self.agent_id = agent_id
        self.mode = mode
        self.poll_interval = poll_interval
        self.approval_timeout = approval_timeout
        self.name = wrapped_tool.name
        self.description = getattr(wrapped_tool, "description", "")
        self.args_schema = getattr(wrapped_tool, "args_schema", None)
        self.return_direct = getattr(wrapped_tool, "return_direct", False)

    def _resource_from_args(self, *args: Any, **kwargs: Any) -> str:
        if args:
            return str(args[0])
        if kwargs:
            return str(kwargs)
        return "unknown"

    def _evaluate(self, *args: Any, **kwargs: Any) -> Any:
        """Return either the evaluation result (on ALLOW), a
        ``PendingApprovalResult`` (non-blocking + APPROVAL_REQUIRED), or
        raise ``ToolException`` on DENY / rejected-after-block.
        """
        resource = self._resource_from_args(*args, **kwargs)
        result = self.agr_client.evaluate(
            agent=self.agent_id,
            action=self.wrapped_tool.name,
            resource=resource,
            context=dict(kwargs),
        )
        if result.decision == "DENY":
            raise ToolException(f"AGR blocked: {result.reason}")
        if result.decision == "APPROVAL_REQUIRED":
            if not result.approval_id:
                raise ToolException("AGR approval required but no approval_id returned.")
            if self.mode == "non_blocking":
                if _PendingApprovalResult is None:
                    raise ToolException(
                        "agr-sdk-python is not installed; cannot build PendingApprovalResult."
                    )
                return _PendingApprovalResult(
                    approval_id=result.approval_id,
                    action=self.wrapped_tool.name,
                    resource=resource,
                    reason=result.reason,
                    eval_id=result.eval_id,
                )
            # block_until_resolved: poll and either proceed or raise.
            approved = self.agr_client.wait_for_approval(
                result.approval_id,
                poll_interval=self.poll_interval,
                timeout=self.approval_timeout,
            )
            if not approved:
                raise ToolException(
                    f"AGR approval rejected for {self.wrapped_tool.name} (id={result.approval_id})"
                )
        return result

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        outcome = self._evaluate(*args, **kwargs)
        if _PendingApprovalResult is not None and isinstance(outcome, _PendingApprovalResult):
            return outcome
        return self.wrapped_tool._run(*args, **kwargs)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        outcome = self._evaluate(*args, **kwargs)
        if _PendingApprovalResult is not None and isinstance(outcome, _PendingApprovalResult):
            return outcome
        return await self.wrapped_tool._arun(*args, **kwargs)


def guard_tools(
    tools: list[BaseTool],
    agr_client: AGRClient,
    agent_id: str,
    *,
    mode: GuardMode = "non_blocking",
) -> list[AGRToolGuard]:
    return [
        AGRToolGuard(agr_client=agr_client, wrapped_tool=tool, agent_id=agent_id, mode=mode)
        for tool in tools
    ]
