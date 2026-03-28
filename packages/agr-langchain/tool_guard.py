"""LangChain tool wrapper that consults AGR before execution."""

from __future__ import annotations

from typing import Any

from agr.client import AGRClient

try:
    from langchain_core.tools import BaseTool, ToolException
except ImportError:  # pragma: no cover - optional dependency
    class ToolException(Exception):
        pass

    class BaseTool:  # type: ignore[no-redef]
        name: str = "tool"
        description: str = ""

        def _run(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def _arun(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError


class AGRToolGuard(BaseTool):
    agr_client: AGRClient
    wrapped_tool: BaseTool
    agent_id: str

    def __init__(self, agr_client: AGRClient, wrapped_tool: BaseTool, agent_id: str) -> None:
        super().__init__()
        self.agr_client = agr_client
        self.wrapped_tool = wrapped_tool
        self.agent_id = agent_id
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

    def _evaluate(self, *args: Any, **kwargs: Any):
        result = self.agr_client.evaluate(
            agent=self.agent_id,
            action=self.wrapped_tool.name,
            resource=self._resource_from_args(*args, **kwargs),
            context={k: v for k, v in kwargs.items()},
        )
        if result.decision == "DENY":
            raise ToolException(f"AGR blocked: {result.reason}")
        if result.decision == "APPROVAL_REQUIRED":
            raise ToolException(f"AGR approval required: {result.approval_id}")
        return result

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        self._evaluate(*args, **kwargs)
        return self.wrapped_tool._run(*args, **kwargs)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        self._evaluate(*args, **kwargs)
        return await self.wrapped_tool._arun(*args, **kwargs)


def guard_tools(tools: list[BaseTool], agr_client: AGRClient, agent_id: str) -> list[AGRToolGuard]:
    return [AGRToolGuard(agr_client=agr_client, wrapped_tool=tool, agent_id=agent_id) for tool in tools]
