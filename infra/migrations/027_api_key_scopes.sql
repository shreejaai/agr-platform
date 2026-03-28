-- Migration 027: scoped API keys

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    key_prefix VARCHAR(12) NOT NULL,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    name VARCHAR(128) NOT NULL,
    created_by VARCHAR(256) NOT NULL,
    last_used_at TIMESTAMPTZ NULL,
    expires_at TIMESTAMPTZ NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO api_keys (org_id, key_hash, key_prefix, scopes, name, created_by)
SELECT
    organizations.id,
    encode(digest(organizations.api_key, 'sha256'), 'hex'),
    left(organizations.api_key, 12),
    '["*"]'::jsonb,
    'Legacy org key',
    'migration'
FROM organizations
WHERE organizations.api_key IS NOT NULL
ON CONFLICT (key_hash) DO NOTHING;

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY api_keys_isolation ON api_keys
    USING (org_id::text = current_setting('app.current_org_id', true));
