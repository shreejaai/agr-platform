"""Basic evaluate example using the AGR Python SDK.

Usage:
    pip install agr-sdk
    AGR_API_KEY=agr_sk_... python 01_basic_evaluate.py
"""

import os
import sys

sys.path.insert(0, "../../packages/agr-core")

import httpx

AGR_BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")
AGR_API_KEY = os.environ.get("AGR_API_KEY", "")

if not AGR_API_KEY:
    print("ERROR: Set AGR_API_KEY environment variable")
    sys.exit(1)

headers = {"Authorization": f"Bearer {AGR_API_KEY}"}

cases = [
    {
        "label": "Low-risk read (expect ALLOW)",
        "payload": {
            "agent_id": "trusted-reader",
            "action": "read",
            "resource": "docs/readme.txt",
            "context": {},
        },
    },
    {
        "label": "Production db.drop (expect DENY)",
        "payload": {
            "agent_id": "coder-001",
            "action": "db.drop",
            "resource": "prod-db",
            "context": {"environment": "production"},
        },
    },
    {
        "label": "Staging deploy (expect ALLOW)",
        "payload": {
            "agent_id": "deploy-bot",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
    },
]

with httpx.Client(base_url=AGR_BASE_URL, headers=headers) as client:
    for case in cases:
        resp = client.post("/v1/evaluate", json=case["payload"])
        data = resp.json()
        decision = data.get("decision", "ERROR")
        risk = data.get("risk_level", "n/a")
        print(f"[{decision:20s}] risk={risk:6s}  {case['label']}")
        if data.get("compliance_findings"):
            violations = [f for f in data["compliance_findings"] if not f["passed"]]
            if violations:
                for v in violations:
                    print(f"  ⚠  [{v['standard']}/{v['rule_id']}] {v['message']}")
