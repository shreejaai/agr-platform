"""AGR + CrewAI — AGRToolWrapper pattern for governed tool execution.

This example shows how to wrap any callable with AGR governance using a
reusable wrapper class. No actual CrewAI import is needed — the pattern
mirrors how you would use it in a real CrewAI agent.
"""

import os
from collections.abc import Callable
from typing import Any

from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)


# ---------------------------------------------------------------------------
# AGRToolWrapper — drop this into any CrewAI agent's tool list
# ---------------------------------------------------------------------------


class AGRToolWrapper:
    """Wraps a callable tool with AGR governance.

    Usage:
        raw_tool = my_database_query_fn
        safe_tool = AGRToolWrapper(
            tool=raw_tool,
            action="query_database",
            resource="customers-db",
            agent_id="crewai-researcher",
        )
        result = safe_tool(query="SELECT * FROM customers LIMIT 10")
    """

    def __init__(
        self,
        tool: Callable,
        action: str,
        resource: str,
        agent_id: str,
        base_context: dict[str, Any] | None = None,
    ) -> None:
        self.tool = tool
        self.action = action
        self.resource = resource
        self.agent_id = agent_id
        self.base_context = base_context or {}
        self.__name__ = getattr(tool, "__name__", action)
        self.__doc__ = getattr(tool, "__doc__", f"AGR-governed {action}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ctx = dict(self.base_context)
        # Merge any keyword args that look like context signals
        ctx.update({k: v for k, v in kwargs.items() if isinstance(v, str | int | float | bool)})

        result = agr.evaluate(
            agent=self.agent_id,
            action=self.action,
            resource=self.resource,
            context=ctx,
        )

        print(f"  [AGR] {self.action} → {result.decision} (risk={result.risk_score})")

        if result.allowed:
            return self.tool(*args, **kwargs)
        elif result.requires_approval:
            print(f"  [AGR] ⏳ Waiting for approval (id: {result.approval_id})...")
            approved = agr.wait_for_approval(result.approval_id, timeout=120)
            if approved:
                return self.tool(*args, **kwargs)
            raise PermissionError(f"Tool '{self.action}' approval rejected or timed out")
        else:
            raise PermissionError(f"Tool '{self.action}' blocked by AGR policy: {result.reason}")


# ---------------------------------------------------------------------------
# Mock tools — stand-ins for real CrewAI tools
# ---------------------------------------------------------------------------


def query_database(query: str) -> str:
    return f"[mock DB] Results for: {query}"


def send_email(to: str, subject: str, body: str) -> str:
    return f"[mock email] Sent '{subject}' to {to}"


def read_file(path: str) -> str:
    return f"[mock fs] Contents of {path}"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def main() -> None:
    print("=== AGR + CrewAI Tool Wrapper Demo ===\n")

    # Wrap tools with governance
    safe_db = AGRToolWrapper(
        tool=query_database,
        action="query_database",
        resource="customers-db",
        agent_id="crewai-researcher",
        base_context={"sensitivity": "high"},
    )

    safe_email = AGRToolWrapper(
        tool=send_email,
        action="send_email",
        resource="email-service",
        agent_id="crewai-outreach-agent",
    )

    safe_read = AGRToolWrapper(
        tool=read_file,
        action="read_ticket_status",
        resource="ticket-fs",
        agent_id="crewai-support-agent",
    )

    # Scenario 1: Safe read — should ALLOW
    print("--- Scenario 1: Read ticket status (expect ALLOW) ---")
    try:
        output = safe_read(path="tickets/1234.json")
        print(f"  Output: {output}")
    except PermissionError as exc:
        print(f"  🚫 Blocked: {exc}")

    print()

    # Scenario 2: DB query — may trigger approval depending on policies
    print("--- Scenario 2: Query customer DB (depends on active policies) ---")
    try:
        output = safe_db(query="SELECT email FROM customers")
        print(f"  Output: {output}")
    except PermissionError as exc:
        print(f"  🚫 Blocked: {exc}")

    print()

    # Scenario 3: Send email — evaluated against AGR
    print("--- Scenario 3: Send email via governed wrapper ---")
    try:
        output = safe_email(
            to="user@example.com",
            subject="Your report",
            body="Please find the report attached.",
        )
        print(f"  Output: {output}")
    except PermissionError as exc:
        print(f"  🚫 Blocked: {exc}")

    print()
    print("✅ CrewAI governance demo complete")


if __name__ == "__main__":
    main()
