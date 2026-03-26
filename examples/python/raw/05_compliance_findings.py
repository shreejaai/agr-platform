"""Compliance findings demo — shows EU AI Act / SOC2 / ISO 42001 findings.

Usage:
    AGR_API_KEY=agr_sk_... python 05_compliance_findings.py
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

test_cases = [
    # (description, agent_id, action, resource, context)
    ("Compliant request", "my-agent-v2", "read", "report.pdf", {}),
    ("Generic agent ID (warning)", "bot", "deploy", "server", {"environment": "staging"}),
    ("Wildcard action (warning)", "agent-001", "*", "resource", {}),
    ("DENY with no context", "agent-001", "db.drop", "prod-db", {"environment": "production"}),
]

with httpx.Client(base_url=AGR_BASE_URL, headers=headers, timeout=10) as client:
    for description, agent_id, action, resource, context in test_cases:
        print(f"\n--- {description} ---")
        resp = client.post(
            "/v1/evaluate",
            json={"agent_id": agent_id, "action": action, "resource": resource, "context": context},
        )
        data = resp.json()
        print(f"  Decision: {data['decision']}  Risk: {data.get('risk_level', 'n/a')}")
        findings = data.get("compliance_findings") or []
        if findings:
            for f in findings:
                status = "PASS" if f["passed"] else "FAIL"
                print(f"  [{status}] [{f['standard']}/{f['rule_id']}] {f['message'][:70]}")
        else:
            print("  (no compliance findings)")
