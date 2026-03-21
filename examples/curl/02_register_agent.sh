#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== AGR Register Agent ==="

curl -sX POST "${BASE_URL}/v1/agents/register" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "finance-agent",
    "framework": "langgraph",
    "name": "Finance Agent",
    "description": "Handles vendor payments and transfers",
    "metadata": {
      "owner": "finance-team"
    }
  }' | python3 -m json.tool

echo ""
echo "✅ Agent registered"
