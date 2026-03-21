"""AGR Risk Score Demo — 5 scenarios showing escalating risk scores."""
import os
from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)

SCENARIOS = [
    {
        "label": "Safe read (low risk)",
        "agent": "support-agent",
        "action": "read_ticket_status",
        "resource": "ticket-001",
        "context": {"department": "support"},
    },
    {
        "label": "Deploy to staging (medium risk)",
        "agent": "ci-agent",
        "action": "deploy",
        "resource": "staging-server",
        "context": {"environment": "staging", "branch": "main"},
    },
    {
        "label": "Deploy to production (high risk)",
        "agent": "ci-agent",
        "action": "deploy",
        "resource": "production-server",
        "context": {"environment": "production", "branch": "hotfix-xyz"},
    },
    {
        "label": "Large after-hours transfer (very high risk)",
        "agent": "finance-agent",
        "action": "transfer_funds",
        "resource": "bank-account-001",
        "context": {
            "amount": 99000,
            "is_after_hours": True,
            "destination_country": "IN",
        },
    },
    {
        "label": "Prompt injection detected (critical)",
        "agent": "compromised-agent",
        "action": "export_customer_db",
        "resource": "customers-table",
        "context": {"prompt_injection_score": 0.97, "reason": "Ignore previous instructions"},
    },
]


def risk_bar(score: float | None, width: int = 20) -> str:
    """Visual bar for risk score 0–100."""
    if score is None:
        return "[" + "?" * width + "]"
    filled = int((score / 100) * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def main() -> None:
    print("=== AGR Risk Score Escalation Demo ===\n")

    # Table header
    print(f"{'#':<3} {'Scenario':<42} {'Decision':<20} {'Score':>5}  {'Level':<10} Bar")
    print("-" * 110)

    for i, scenario in enumerate(SCENARIOS, start=1):
        result = agr.evaluate(
            agent=scenario["agent"],
            action=scenario["action"],
            resource=scenario["resource"],
            context=scenario["context"],
        )

        score = result.risk_score
        level = result.risk_level or "N/A"
        decision = result.decision or "N/A"
        bar = risk_bar(score)

        print(
            f"{i:<3} {scenario['label']:<42} {decision:<20} "
            f"{(str(score) if score is not None else 'N/A'):>5}  {level:<10} {bar}"
        )

    print()
    print("Note: Risk scores and decisions depend on active policies in your org.")
    print("Import starter pack to see varied results: bash ../curl/09_import_policies_json.sh --commit")
    print()
    print("✅ Risk score demo complete")


if __name__ == "__main__":
    main()
