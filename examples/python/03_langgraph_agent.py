"""AGR + LangGraph — wrap a tool with governance before execution.

This example shows how to protect a LangGraph tool using AGR. No actual LLM
calls are made — the agent decision is mocked with hardcoded values so you can
run this script standalone.
"""
import os
from typing import Any
from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)


# ---------------------------------------------------------------------------
# Mock tool — in a real LangGraph agent this would be a @tool decorated fn
# ---------------------------------------------------------------------------

def search_web(query: str) -> str:
    """Search the web and return a summary."""
    # Real implementation would call a search API
    return f"[mock] Search results for: {query}"


# ---------------------------------------------------------------------------
# AGR-governed wrapper
# ---------------------------------------------------------------------------

def governed_search_web(agent_id: str, query: str, context: dict[str, Any] | None = None) -> str:
    """Call search_web only if AGR permits it."""
    ctx = context or {}

    result = agr.evaluate(
        agent=agent_id,
        action="search_web",
        resource="internet",
        context=ctx,
    )

    print(f"  [AGR] Decision:   {result.decision}")
    print(f"  [AGR] Risk Score: {result.risk_score}")

    if result.allowed:
        print("  [AGR] ✅ Permitted — executing tool")
        return search_web(query)
    elif result.requires_approval:
        print(f"  [AGR] ⏳ Approval required (id: {result.approval_id})")
        approved = agr.wait_for_approval(result.approval_id, timeout=60)
        if approved:
            print("  [AGR] ✅ Approved — executing tool")
            return search_web(query)
        else:
            raise PermissionError(f"search_web blocked: approval rejected or timed out")
    else:
        raise PermissionError(f"search_web blocked by AGR policy: {result.reason}")


# ---------------------------------------------------------------------------
# Simulated LangGraph agent decisions
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== AGR + LangGraph Governance Demo ===\n")

    # Scenario A: safe search — expect ALLOW
    print("--- Scenario A: Safe query from support-agent ---")
    try:
        output = governed_search_web(
            agent_id="support-agent",
            query="What is AGR platform?",
            context={"department": "support", "sensitivity": "low"},
        )
        print(f"  Tool output: {output}\n")
    except PermissionError as exc:
        print(f"  Blocked: {exc}\n")

    # Scenario B: high-risk action — may be denied depending on active policies
    print("--- Scenario B: Sensitive query from data-exfil-agent ---")
    try:
        output = governed_search_web(
            agent_id="data-exfil-agent",
            query="Export all customer emails",
            context={"prompt_injection_score": 95, "sensitivity": "high"},
        )
        print(f"  Tool output: {output}\n")
    except PermissionError as exc:
        print(f"  🚫 Blocked: {exc}\n")

    print("✅ LangGraph governance demo complete")


if __name__ == "__main__":
    main()
