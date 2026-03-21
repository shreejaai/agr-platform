"""Audit trail demo — run several evaluations then verify hash-chain integrity.

Usage:
    AGR_API_KEY=agr_sk_... python 06_audit_trail.py
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

evals = [
    ("agent-a", "read", "file1.txt", {}),
    ("agent-b", "write", "file2.txt", {"environment": "staging"}),
    ("agent-c", "db.drop", "staging-db", {"environment": "staging"}),
]

with httpx.Client(base_url=AGR_BASE_URL, headers=headers, timeout=10) as client:
    print("Step 1: Running evaluations...")
    for agent_id, action, resource, context in evals:
        r = client.post(
            "/v1/evaluate",
            json={"agent_id": agent_id, "action": action, "resource": resource, "context": context},
        )
        d = r.json()
        print(f"  {agent_id:<12} {action:<10} → {d['decision']}")

    print("\nStep 2: Retrieving audit log...")
    r = client.get("/v1/audit?limit=20")
    events = r.json()
    print(f"  Total events retrieved: {len(events)}")
    for e in events[:5]:
        print(f"  #{e['sequence_num']:4d} [{e['event_type']:20s}] {e['agent_id']}")

    print("\nStep 3: Verifying hash chain integrity...")
    r = client.get("/v1/audit/verify")
    result = r.json()
    valid = result["valid"]
    total = result["total"]
    print(f"  Chain valid: {valid}  Total events: {total}")
    if not valid:
        print(f"  First invalid sequence: {result.get('first_invalid_sequence')}")
    else:
        print("  All audit entries are cryptographically linked and unmodified.")
