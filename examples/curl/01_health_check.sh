#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"

echo "=== AGR Health Check ==="

curl -sf "${BASE_URL}/health" | python3 -m json.tool

echo ""
echo "✅ AGR daemon is healthy"
