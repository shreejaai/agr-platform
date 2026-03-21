#!/usr/bin/env bash
set -euo pipefail

echo "=== AGR Setup — Creating test org ==="

API_KEY=$(docker exec agr-platform-postgres-1 psql -U agr_svc_usr -d agr_platform -tAc "
  INSERT INTO organizations (id, name, slug, api_key, eval_limit, eval_week_start)
  VALUES (
    gen_random_uuid(), 'Demo Org', 'demo-org',
    'agr_sk_' || encode(gen_random_bytes(24), 'hex'), 0, NOW()
  )
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING api_key;
")

export AGR_API_KEY="$API_KEY"

echo ""
echo "✅ Org created. Add to your shell:"
echo "  export AGR_API_KEY=\"$AGR_API_KEY\""
