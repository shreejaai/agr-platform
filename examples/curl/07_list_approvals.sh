#!/usr/bin/env bash
# Demo: List pending approval requests

curl -s "${AGR_BASE_URL:-http://localhost:8000}/v1/approvals?status=pending" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool
