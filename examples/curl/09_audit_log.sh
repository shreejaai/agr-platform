#!/usr/bin/env bash
# Demo: Retrieve audit log with hash-chain verification

echo "=== Recent audit events ==="
curl -s "${AGR_BASE_URL:-http://localhost:8000}/v1/audit?limit=10" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool

echo ""
echo "=== Audit chain integrity verification ==="
curl -s "${AGR_BASE_URL:-http://localhost:8000}/v1/audit/verify" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool
