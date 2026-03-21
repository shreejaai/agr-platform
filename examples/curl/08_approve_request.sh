#!/usr/bin/env bash
# Demo: Approve a pending request by ID
# Usage: APPROVAL_ID=<uuid> bash 08_approve_request.sh

APPROVAL_ID="${APPROVAL_ID:?Set APPROVAL_ID environment variable}"

curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/approvals/${APPROVAL_ID}/decide" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "approved",
    "decided_by": "ops-engineer",
    "reason": "Verified safe to proceed."
  }' | python3 -m json.tool
