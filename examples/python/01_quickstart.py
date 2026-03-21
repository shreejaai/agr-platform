"""AGR Quickstart — protect any AI agent tool call in 3 lines."""

import os

from agr import AGRClient

api_key = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
agr = AGRClient(api_key=api_key, base_url=os.environ.get("AGR_BASE_URL", "http://localhost:8000"))

result = agr.evaluate(
    agent="support-agent",
    action="read_ticket_status",
    resource="ticket-12345",
    context={"department": "support"},
)

print(f"Decision:   {result.decision}")
print(f"Risk Score: {result.risk_score}")
print(f"Risk Level: {result.risk_level}")

if result.allowed:
    print("✅ Agent may execute this action")
elif result.requires_approval:
    print(f"⏳ Approval required (id: {result.approval_id})")
    approved = agr.wait_for_approval(result.approval_id, timeout=120)
    print("✅ Approved!" if approved else "❌ Rejected or timed out")
else:
    print(f"🚫 Blocked: {result.reason}")
