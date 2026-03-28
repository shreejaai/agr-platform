-- Migration 026: per-org compliance enforcement configuration

CREATE TABLE IF NOT EXISTS org_compliance_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plugin_id VARCHAR(64) NOT NULL,
    enforcement_mode VARCHAR(16) NOT NULL DEFAULT 'advisory',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, plugin_id)
);

ALTER TABLE org_compliance_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_compliance_configs_isolation ON org_compliance_configs
    USING (org_id::text = current_setting('app.current_org_id', true));
