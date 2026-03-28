#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

export AGR_API_KEY="${AGR_API_KEY:-${API_KEY:-}}"
BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

if [ -z "${AGR_API_KEY}" ]; then
  echo "AGR_API_KEY is required"
  exit 1
fi

# Expected output: a JSON decision response with ALLOW, DENY, or APPROVAL_REQUIRED.
curl -s \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/evaluate" \
  -d '{
    "agent_id": "example-agent",
    "action": "read_docs",
    "resource": "getting-started",
    "context": {"environment": "development", "risk_level": "low"}
  }' | python3 -m json.tool
