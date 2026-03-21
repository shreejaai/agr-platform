#!/usr/bin/env bash
# Demo: List all Cedar policies for your org

curl -s "${AGR_BASE_URL:-http://localhost:8000}/v1/policies" \
  -H "Authorization: Bearer ${AGR_API_KEY}" | python3 -m json.tool
