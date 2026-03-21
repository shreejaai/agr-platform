"""AGR Approval Flow — full lifecycle with background auto-approve."""
import os
import time
import threading
import httpx
from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)


def auto_approve(approval_id: str, delay: float = 3.0) -> None:
    """Simulate a human approver by auto-approving after a short delay."""
    time.sleep(delay)
    print(f"\n  [auto-approver] Approving {approval_id}...")
    try:
        resp = httpx.post(
            f"{BASE_URL}/v1/approvals/{approval_id}/approve",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"comment": "Auto-approved by demo script"},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  [auto-approver] Done — status {resp.status_code}")
    except Exception as exc:
        print(f"  [auto-approver] Error: {exc}")


def main() -> None:
    print("=== AGR Approval Flow Demo ===\n")

    # Step 1: Evaluate a large fund transfer
    print("--- Step 1: Evaluate transfer_funds ($50,000) ---")
    result = agr.evaluate(
        agent="finance-agent",
        action="transfer_funds",
        resource="bank-account-001",
        context={
            "amount": 50000,
            "destination": "vendor-acct-xyz",
            "destination_country": "IN",
        },
    )
    print(f"  Decision:    {result.decision}")
    print(f"  Approval ID: {result.approval_id}")
    print(f"  Risk Score:  {result.risk_score}")

    if not result.requires_approval:
        print(f"\n  ⚠️  Expected APPROVAL_REQUIRED, got {result.decision}")
        print("  Import finance_controls policies first: bash ../curl/08_import_policies_yaml.sh --commit")
        return

    print("\n✅ APPROVAL_REQUIRED — waiting for human (auto-approve in 3s)...")

    # Step 2: Launch background auto-approver
    print("\n--- Step 2: Starting background approver thread ---")
    approver = threading.Thread(
        target=auto_approve,
        args=(result.approval_id,),
        daemon=True,
    )
    approver.start()

    # Step 3: Wait for approval
    print("\n--- Step 3: Polling for approval decision ---")
    approved = agr.wait_for_approval(result.approval_id, timeout=30)
    approver.join(timeout=5)

    if approved:
        print("\n✅ Transfer approved — agent may now execute")
    else:
        print("\n❌ Transfer rejected or timed out")

    # Step 4: Verify audit trail
    print("\n--- Step 4: Recent audit events ---")
    import httpx as _httpx
    audit_resp = _httpx.get(
        f"{BASE_URL}/v1/audit?limit=5",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=10,
    )
    audit_resp.raise_for_status()
    events = audit_resp.json()
    items = events if isinstance(events, list) else events.get("items", [])
    for event in items[:5]:
        print(f"  [{event.get('event_type','?'):25s}] agent={event.get('agent_id','?')} action={event.get('action','?')}")

    print("\n✅ Approval lifecycle complete")


if __name__ == "__main__":
    main()
