#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

# Default to dry-run; pass --commit to actually import
DRY_RUN=true
if [ "${1:-}" = "--commit" ]; then
  DRY_RUN=false
fi

echo "=== Import Starter Pack (JSON, dry_run=$DRY_RUN) ==="
echo ""

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
    },
    {
      "name": "deny-deploy-prod-by-default",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"deploy\", resource) when { context has environment && context.environment == \"production\" };",
      "active": true
    },
    {
      "name": "require-approval-deploy-prod-release-manager",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"deploy\", resource) when { context has environment && context.environment == \"production\" } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-delete-prod-database",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"delete_database\", resource) when { context has environment && context.environment == \"prod\" };",
      "active": true
    },
    {
      "name": "require-approval-scale-prod-cluster",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"scale_cluster\", resource) when { context has environment && context.environment == \"prod\" } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-modify-prod-config",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"modify_config\", resource) when { context has environment && context.environment == \"prod\" } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-export-customer-db",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"export_customer_db\", resource);",
      "active": true
    },
    {
      "name": "require-approval-confidential-data",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"read_data\", resource) when { context has sensitivity && context.sensitivity == \"high\" } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-read-data-outside-department",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"read_data\", resource) when { context has department_match && context.department_match == false };",
      "active": true
    },
    {
      "name": "deny-hr-salary-write",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"write_salary_record\", resource);",
      "active": true
    },
    {
      "name": "allow-read-ticket-status",
      "level": "org",
      "cedar_rule": "permit(principal, action == Action::\"read_ticket_status\", resource);",
      "active": true
    },
    {
      "name": "deny-prompt-injection-high",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"execute_tool\", resource) when { context has prompt_injection_score && context.prompt_injection_score >= 80 };",
      "active": true
    },
    {
      "name": "require-approval-geo-anomaly",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"execute_tool\", resource) when { context has geo_anomaly && context.geo_anomaly == true } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "require-approval-repeated-denials",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"execute_tool\", resource) when { context has recent_denials && context.recent_denials >= 5 } unless { context has approval_status && context.approval_status == \"approved\" };",
      "active": true
    },
    {
      "name": "deny-export-with-injection",
      "level": "org",
      "cedar_rule": "forbid(principal, action == Action::\"export_customer_db\", resource) when { context has prompt_injection_score };",
      "active": true
    }
  ],
  "dry_run": DRY_RUN_PLACEHOLDER,
  "overwrite": false
}
EOF
)

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
  echo "✅ Starter pack (20 policies) imported"
fi
