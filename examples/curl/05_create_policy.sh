#!/usr/bin/env bash
# Demo: Create a new Cedar policy — block all production file deletions

curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/policies" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Block production file deletions",
    "level": "org",
    "cedar_rule": "forbid(principal, action == Action::\"file.delete\", resource) when { context has environment && context.environment == \"production\" };"
  }' | python3 -m json.tool
