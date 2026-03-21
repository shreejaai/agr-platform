"""AGR Full Scenario Test Suite — automated PASS/FAIL validation.

Exit code 0 if all tests pass, 1 if any fail.
"""

import os
import sys
import threading
import time

import httpx
from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, note: str = "") -> None:
    RESULTS.append((name, passed, note))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {note}" if note else ""))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_safe_read() -> None:
    result = agr.evaluate(
        agent="support-agent",
        action="read_ticket_status",
        resource="ticket-12345",
        context={"department": "support"},
    )
    passed = result.decision in ("ALLOW", "APPROVAL_REQUIRED")
    record("test_safe_read", passed, f"decision={result.decision}")


def test_deploy_prod_denied() -> None:
    result = agr.evaluate(
        agent="ci-agent",
        action="deploy",
        resource="production-server",
        context={"environment": "production"},
    )
    # DENY or APPROVAL_REQUIRED are both acceptable — must not be plain ALLOW
    passed = result.decision in ("DENY", "APPROVAL_REQUIRED")
    record(
        "test_deploy_prod_denied",
        passed,
        f"decision={result.decision} (expected DENY or APPROVAL_REQUIRED)",
    )


def test_export_denied() -> None:
    result = agr.evaluate(
        agent="compromised-agent",
        action="export_customer_db",
        resource="customers-table",
        context={"prompt_injection_score": 0.95},
    )
    passed = result.decision == "DENY"
    record("test_export_denied", passed, f"decision={result.decision}")


def test_risk_score_present() -> None:
    result = agr.evaluate(
        agent="test-agent",
        action="read_data",
        resource="some-resource",
        context={},
    )
    passed = result.risk_score is not None
    record("test_risk_score_present", passed, f"risk_score={result.risk_score}")


def test_register_agent() -> None:
    try:
        registered = agr.register_agent(
            agent_id="test-agent-registration",
            name="Test Agent",
            framework="custom",
            description="Created by 07_full_scenario_test.py",
        )
        passed = registered is not None
        record("test_register_agent", passed, f"agent_id={getattr(registered,'agent_id','?')}")
    except Exception as exc:
        record("test_register_agent", False, str(exc))


def test_approval_lifecycle() -> None:
    """Evaluate → auto-approve → wait_for_approval."""
    result = agr.evaluate(
        agent="finance-agent",
        action="transfer_funds",
        resource="bank-account-001",
        context={"amount": 50000, "destination_country": "IN"},
    )

    if result.decision == "ALLOW":
        # No approval policy active — skip gracefully
        record(
            "test_approval_lifecycle",
            True,
            "skipped — no approval policy active (import finance_controls first)",
        )
        return

    if result.decision != "APPROVAL_REQUIRED":
        record(
            "test_approval_lifecycle",
            False,
            f"expected APPROVAL_REQUIRED or ALLOW, got {result.decision}",
        )
        return

    approval_id = result.approval_id

    def do_approve() -> None:
        time.sleep(2)
        try:
            resp = httpx.post(
                f"{BASE_URL}/v1/approvals/{approval_id}/approve",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={"comment": "Auto-approved by test suite"},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            print(f"    [auto-approve error] {exc}")

    t = threading.Thread(target=do_approve, daemon=True)
    t.start()

    approved = agr.wait_for_approval(approval_id, timeout=20)
    t.join(timeout=5)

    record("test_approval_lifecycle", approved, f"approval_id={approval_id}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def main() -> int:
    print("=== AGR Full Scenario Test Suite ===\n")

    tests = [
        test_safe_read,
        test_deploy_prod_denied,
        test_export_denied,
        test_risk_score_present,
        test_register_agent,
        test_approval_lifecycle,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as exc:
            record(test_fn.__name__, False, f"uncaught exception: {exc}")

    # Summary
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed

    print()
    print("=" * 55)
    print(f"  Total: {len(RESULTS)}   PASS: {passed}   FAIL: {failed}")
    print("=" * 55)

    if failed == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ {failed} test(s) failed.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
