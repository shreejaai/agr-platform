"""AGR Python quickstart flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agr-sdk-python"))
from agr.client import AGRClient


def main() -> None:
    client = AGRClient(
        api_key=os.environ.get("AGR_API_KEY"),
        base_url=os.environ.get("AGR_BASE_URL", "http://localhost:8000"),
    )

    agent = client.register_agent("example-agent", {"framework": "quickstart"})
    print("Registered agent:", agent.get("agent_id"))

    allow_result = client.evaluate(
        "example-agent",
        "read_docs",
        "getting-started",
        {"environment": "development", "risk_level": "low"},
    )
    print("Low-risk decision:", allow_result.decision, "-", allow_result.reason)

    approval_result = client.evaluate(
        "example-agent",
        "deploy",
        "checkout-service",
        {"environment": "production"},
    )
    print("Sensitive decision:", approval_result.decision, "-", approval_result.reason)

    if approval_result.approval_id:
        try:
            approved = client.wait_for_approval(approval_result.approval_id, timeout=5.0)
            print("Approval resolved:", "approved" if approved else "rejected")
        except TimeoutError:
            print("Approval still pending after 5 seconds. Exiting gracefully.")

    client.close()


if __name__ == "__main__":
    main()
