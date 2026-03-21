"""Risk scoring demo — shows how the risk engine scores different requests.

Usage:
    AGR_API_KEY=agr_sk_... python 03_risk_scoring_demo.py
"""

import os
import sys

import httpx

AGR_BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")
AGR_API_KEY = os.environ.get("AGR_API_KEY", "")

if not AGR_API_KEY:
    print("ERROR: Set AGR_API_KEY")
    sys.exit(1)

headers = {"Authorization": f"Bearer {AGR_API_KEY}"}

requests = [
    ("trusted-reader", "read", "reports/q1.csv", {}),
    ("agent-001", "write", "customer-data", {"count": 100}),
    ("agent-9999", "delete", "user-records", {"environment": "production", "count": 50000}),
    ("bot", "deploy", "production-server", {"environment": "production", "force": "true"}),
    ("trusted-agent", "deploy", "staging-server", {"environment": "staging"}),
]

BAR_WIDTH = 30

print(f"{'Agent':<22} {'Action':<10} {'Score':>5}  {'Level':<8}  Bar")
print("-" * 80)

with httpx.Client(base_url=AGR_BASE_URL, headers=headers, timeout=10) as client:
    for agent_id, action, resource, context in requests:
        resp = client.post(
            "/v1/evaluate",
            json={
                "agent_id": agent_id,
                "action": action,
                "resource": resource,
                "context": context,
            },
        )
        data = resp.json()
        score = data.get("risk_score", 0) or 0
        level = data.get("risk_level", "n/a")
        bar_fill = round(score / 100 * BAR_WIDTH)
        bar = "█" * bar_fill + "░" * (BAR_WIDTH - bar_fill)
        print(f"{agent_id:<22} {action:<10} {score:>5}  {level:<8}  {bar}")
