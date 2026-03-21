#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== Verify Audit Chain Integrity ==="

RESPONSE=$(curl -s "${BASE_URL}/v1/audit/verify" \
  -H "Authorization: Bearer ${AGR_API_KEY}")

echo "$RESPONSE" | python3 -m json.tool

VALID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('valid',''))")
TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total', 0))")

echo ""
echo "Valid:        $VALID"
echo "Total events: $TOTAL"

if [ "$VALID" = "True" ] || [ "$VALID" = "true" ]; then
  echo "✅ PASS — audit chain is intact (SHA-256 hash chain verified)"
else
  echo "❌ FAIL — audit chain integrity check failed"
  exit 1
fi
