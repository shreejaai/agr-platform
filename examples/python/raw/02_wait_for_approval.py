"""Wait-for-approval demo — simulates a production deploy gated by human sign-off.

Flow:
1. POST /evaluate → APPROVAL_REQUIRED
2. Poll GET /approvals/{id} until status != pending
3. Proceed or abort based on decision

Usage:
    AGR_API_KEY=agr_sk_... APPROVER_EMAIL=ops@example.com python 02_wait_for_approval.py
"""

import os
import sys
import time

import httpx

AGR_BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")
AGR_API_KEY = os.environ.get("AGR_API_KEY", "")
APPROVER_EMAIL = os.environ.get("APPROVER_EMAIL", "")

if not AGR_API_KEY:
    print("ERROR: Set AGR_API_KEY")
    sys.exit(1)

headers = {"Authorization": f"Bearer {AGR_API_KEY}"}

with httpx.Client(base_url=AGR_BASE_URL, headers=headers, timeout=10) as client:
    print("Step 1: Requesting evaluation for production deploy...")
    resp = client.post(
        "/v1/evaluate",
        json={
            "agent_id": "deploy-bot",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production", "version": "2.0.0"},
            "approver_email": APPROVER_EMAIL or None,
        },
    )
    data = resp.json()
    decision = data.get("decision")
    print(f"  Decision: {decision}")

    if decision != "APPROVAL_REQUIRED":
        print(f"  No approval needed (decision={decision}). Done.")
        sys.exit(0)

    approval_id = data.get("approval_id")
    print(f"  Approval request created: {approval_id}")
    if APPROVER_EMAIL:
        print(f"  Email sent to: {APPROVER_EMAIL}")
    print()
    print("Step 2: Polling for decision (Ctrl+C to cancel)...")

    for attempt in range(30):  # poll up to 5 minutes
        time.sleep(10)
        poll_resp = client.get(f"/v1/approvals/{approval_id}")
        approval = poll_resp.json()
        status = approval.get("status")
        print(f"  [{attempt+1:2d}] status={status}")
        if status in ("approved", "rejected"):
            break
    else:
        print("Timed out waiting for approval decision.")
        sys.exit(1)

    if status == "approved":
        print("\nApproval granted — proceeding with deployment.")
    else:
        print("\nApproval rejected — aborting deployment.")
        sys.exit(1)
