#!/usr/bin/env bash
# Demo: Evaluate — expects DENY for a forbidden production db.drop

curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "coder-001",
    "action": "db.drop",
    "resource": "production-db",
    "context": {"environment": "production"}
  }' | python3 -m json.tool
