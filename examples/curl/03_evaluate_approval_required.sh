#!/usr/bin/env bash
# Demo: Evaluate — triggers APPROVAL_REQUIRED for a production deploy
# Pass approver_email to receive an email with approve/reject links.

curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "deploy-bot",
    "action": "deploy",
    "resource": "production-server",
    "context": {"environment": "production", "version": "1.2.3"},
    "approver_email": "ops@example.com"
  }' | python3 -m json.tool
