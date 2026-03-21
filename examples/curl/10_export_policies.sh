#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== Export Active Policies ==="

curl -s "${BASE_URL}/v1/policies/export?active_only=true" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool

echo ""
echo "✅ Policy export complete"
