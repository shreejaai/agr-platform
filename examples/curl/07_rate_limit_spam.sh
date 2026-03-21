#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

BASE_URL="${AGR_BASE_URL:-http://localhost:8000}"
REQUESTS=120

echo "=== Rate Limit Stress Test — Sending $REQUESTS rapid requests ==="
echo "Note: 429s only appear when org eval_limit > 0. With eval_limit=0 all will be 200."
echo ""

OK=0
RATE_LIMITED=0
OTHER=0

for i in $(seq 1 $REQUESTS); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/v1/evaluate" \
    -H "Authorization: Bearer ${AGR_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"agent_id\":\"stress-agent\",\"action\":\"read_data\",\"resource\":\"resource-${i}\",\"context\":{}}")

  case "$STATUS" in
    200) OK=$((OK + 1)) ;;
    429) RATE_LIMITED=$((RATE_LIMITED + 1)) ;;
    *)   OTHER=$((OTHER + 1)) ;;
  esac

  # Print progress every 20 requests
  if (( i % 20 == 0 )); then
    echo "  Progress: $i / $REQUESTS  (200: $OK  429: $RATE_LIMITED  other: $OTHER)"
  fi
done

echo ""
echo "=== Summary ==="
echo "  Total requests:  $REQUESTS"
echo "  HTTP 200 (OK):   $OK"
echo "  HTTP 429 (rate limited): $RATE_LIMITED"
echo "  Other:           $OTHER"

if [ "$RATE_LIMITED" -gt 0 ]; then
  echo ""
  echo "✅ Rate limiting is active — $RATE_LIMITED requests were throttled"
else
  echo ""
  echo "ℹ️  No rate limiting triggered (eval_limit=0 means unlimited)"
fi
