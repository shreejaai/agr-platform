#!/usr/bin/env bash
# Demo: Basic evaluate — expects ALLOW for a low-risk read action
# Prereq: export AGR_API_KEY=agr_sk_yourkey  AGR_BASE_URL=http://localhost:8000

curl -s -X POST "${AGR_BASE_URL:-http://localhost:8000}/v1/evaluate" \
  -H "Authorization: Bearer ${AGR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "trusted-reader-01",
    "action": "read",
    "resource": "docs/getting-started.txt",
    "context": {}
  }' | python3 -m json.tool
