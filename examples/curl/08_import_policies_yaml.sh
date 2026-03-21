#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

# Default to dry-run; pass --commit to actually import
DRY_RUN=true
if [ "${1:-}" = "--commit" ]; then
  DRY_RUN=false
fi

echo "=== Import Finance Controls (dry_run=$DRY_RUN) ==="
echo "Source: ../policy_packs/finance_controls.yaml (converted to AGR JSON format)"
echo ""

# Hardcoded JSON payload — finance_controls policies in PolicyImportItem format
PAYLOAD=$(cat <<'EOF'
{
  "policies": [
    {
      "name": "require-approval-large-transfer",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"transfer_funds\", resource) when { context has amount && context.amount > 25000 } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-international-transfer",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"transfer_funds\", resource) when { context has destination_country && context.destination_country != \"IN\" };",
      "active": true
    },
    {
      "name": "allow-small-internal-transfer",
      "level": "org",
      "cedar_rule": "permit(principal, action == Action::\"transfer_funds\", resource) when { context has amount && context.amount <= 5000 };",
      "active": true
    },
    {
      "name": "deny-transfer-unapproved-vendor",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"transfer_funds\", resource) when { context has vendor_status && context.vendor_status != \"APPROVED\" };",
      "active": true
    },
    {
      "name": "require-approval-after-hours-transfer",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"transfer_funds\", resource) when { context has is_after_hours && context.is_after_hours == true } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-write-finance-without-role",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"write_finance_record\", resource);",
      "active": true
    }
  ],
  "dry_run": DRY_RUN_PLACEHOLDER,
  "overwrite": false
}
EOF
)

# Substitute the dry_run value
PAYLOAD="${PAYLOAD/DRY_RUN_PLACEHOLDER/$DRY_RUN}"

RESPONSE=$(curl -sX POST "${BASE_URL}/v1/policies/import" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

echo "$RESPONSE" | python3 -m json.tool

echo ""
if [ "$DRY_RUN" = "true" ]; then
  echo "ℹ️  Dry run — no policies were saved. Run with --commit to import."
else
  echo "✅ Finance controls imported"
fi
