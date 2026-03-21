#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== Scenario: Safe Read — Expect ALLOW ==="

RESPONSE=$(curl -sX POST "${BASE_URL}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "support-agent",
    "action": "read_ticket_status",
    "resource": "ticket-12345",
    "context": {
      "department": "support"
    }
  }')

echo "$RESPONSE" | python3 -m json.tool

DECISION=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision',''))")
RISK=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('risk_score', 'N/A'))")

echo ""
echo "Decision:   $DECISION"
echo "Risk Score: $RISK"

if [ "$DECISION" = "ALLOW" ]; then
  echo "✅ PASS — got expected ALLOW"
else
  echo "❌ FAIL — expected ALLOW, got $DECISION"
  exit 1
fi
