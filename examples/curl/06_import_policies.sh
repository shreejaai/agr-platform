#!/usr/bin/env bash
# Demo: Bulk import policies (dry_run first, then real import)

echo "=== DRY RUN ==="
curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/policies/import" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": true,
    "policies": [
      {
        "name": "Allow staging deploys",
        "level": "org",
        "cedar_rule": "permit(principal, action == Action::\"deploy\", resource) when { context has environment && context.environment == \"staging\" };"
      },
      {
        "name": "Deny production drops",
        "level": "org",
        "cedar_rule": "forbid(principal, action == Action::\"db.drop\", resource) when { context has environment && context.environment == \"production\" };"
      }
    ]
  }' | python3 -m json.tool

echo ""
echo "=== REAL IMPORT (remove dry_run or set to false) ==="
