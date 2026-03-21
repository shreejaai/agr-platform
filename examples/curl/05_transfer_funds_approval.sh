#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== Scenario: Transfer \$50K — Full Approval Flow ==="
echo ""

# Step 1: Evaluate
echo "--- Step 1: Evaluate transfer_funds ---"
EVAL_RESPONSE=$(curl -sX POST "${BASE_URL}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "finance-agent",
    "action": "transfer_funds",
    "resource": "bank-account-001",
    "context": {
      "amount": 50000,
      "destination": "vendor-acct-xyz",
      "destination_country": "IN"
    }
  }')

echo "$EVAL_RESPONSE" | python3 -m json.tool

DECISION=$(echo "$EVAL_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision',''))")
APPROVAL_ID=$(echo "$EVAL_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('approval_id') or '')")

echo ""
echo "Decision:    $DECISION"
echo "Approval ID: $APPROVAL_ID"

if [ "$DECISION" != "APPROVAL_REQUIRED" ]; then
  echo "❌ FAIL — expected APPROVAL_REQUIRED, got $DECISION"
  exit 1
fi

echo "✅ PASS — APPROVAL_REQUIRED as expected"
echo ""

# Step 2: Check approval status
echo "--- Step 2: Check approval status ---"
curl -sX GET "${BASE_URL}/v1/approvals/${APPROVAL_ID}" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool

echo ""

# Step 3: Approve
echo "--- Step 3: Approve the request ---"
curl -sX POST "${BASE_URL}/v1/approvals/${APPROVAL_ID}/approve" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Approved via curl example — verified vendor"}' | python3 -m json.tool

echo ""

# Step 4: View recent audit events
echo "--- Step 4: Recent audit events ---"
curl -s "${BASE_URL}/v1/audit?limit=5" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool

echo ""
echo "✅ Full approval flow complete"
