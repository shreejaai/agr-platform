"""AGR Policy Import — bulk import with dry-run preview."""
import os
from agr import AGRClient

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)

# Finance controls policy data
FINANCE_POLICIES = [
    {
        "name": "require-approval-large-transfer",
        "level": "org",
        "cedar_rule": (
            'forbid(principal, action == Action::"transfer_funds", resource) '
            "when { context has amount && context.amount > 25000 } "
            'unless { context has approval_status && context.approval_status == "approved" };'
        ),
        "active": True,
    },
    {
        "name": "deny-international-transfer",
        "level": "org",
        "cedar_rule": (
            'forbid(principal, action == Action::"transfer_funds", resource) '
            'when { context has destination_country && context.destination_country != "IN" };'
        ),
        "active": True,
    },
    {
        "name": "allow-small-internal-transfer",
        "level": "org",
        "cedar_rule": (
            'permit(principal, action == Action::"transfer_funds", resource) '
            "when { context has amount && context.amount <= 5000 };"
        ),
        "active": True,
    },
    {
        "name": "deny-transfer-unapproved-vendor",
        "level": "org",
        "cedar_rule": (
            'forbid(principal, action == Action::"transfer_funds", resource) '
            'when { context has vendor_status && context.vendor_status != "APPROVED" };'
        ),
        "active": True,
    },
    {
        "name": "require-approval-after-hours-transfer",
        "level": "org",
        "cedar_rule": (
            'forbid(principal, action == Action::"transfer_funds", resource) '
            "when { context has is_after_hours && context.is_after_hours == true } "
            'unless { context has approval_status && context.approval_status == "approved" };'
        ),
        "active": True,
    },
    {
        "name": "deny-write-finance-without-role",
        "level": "org",
        "cedar_rule": 'forbid(principal, action == Action::"write_finance_record", resource);',
        "active": True,
    },
]


def main() -> None:
    print("=== AGR Policy Import Demo ===\n")

    # Step 1: Dry-run preview
    print("--- Step 1: Dry-run preview (no changes saved) ---")
    dry_result = agr.import_policies(policies=FINANCE_POLICIES, dry_run=True)

    print(f"  Policies to import: {len(FINANCE_POLICIES)}")
    if hasattr(dry_result, "created"):
        print(f"  Would create:  {dry_result.created}")
        print(f"  Would update:  {dry_result.updated}")
        print(f"  Would skip:    {dry_result.skipped}")
        if hasattr(dry_result, "errors") and dry_result.errors:
            print(f"  Errors:        {dry_result.errors}")
    else:
        print(f"  Dry-run response: {dry_result}")

    print()

    # Step 2: Confirm and import for real
    print("--- Step 2: Importing for real (dry_run=False) ---")
    real_result = agr.import_policies(policies=FINANCE_POLICIES, dry_run=False)

    if hasattr(real_result, "created"):
        print(f"  Created: {real_result.created}")
        print(f"  Updated: {real_result.updated}")
        print(f"  Skipped: {real_result.skipped}")
    else:
        print(f"  Import response: {real_result}")

    print()
    print(f"✅ {len(FINANCE_POLICIES)} finance control policies imported")


if __name__ == "__main__":
    main()
