#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== Scenario: Deploy to Production — Expect DENY ==="

RESPONSE=$(curl -sX POST "${BASE_URL}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "ci-agent",
    "action": "deploy",
    "resource": "production-server",
    "context": {
      "environment": "production"
    }
  }')

echo "$RESPONSE" | python3 -m json.tool

DECISION=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision',''))")

echo ""
echo "Decision: $DECISION"

if [ "$DECISION" = "DENY" ]; then
  echo "✅ PASS — got expected DENY"
else
  echo "❌ FAIL — expected DENY, got $DECISION"
  exit 1
fi
