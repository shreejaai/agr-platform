-- Migration 005: Webhook registrations for push notifications on approval decisions

CREATE TABLE webhooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    secret      TEXT NOT NULL,          -- HMAC key: agr_wh_ + 48 hex chars
    events      JSONB NOT NULL DEFAULT '["approval.approved","approval.rejected"]',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_webhooks_org_id ON webhooks(org_id);
CREATE INDEX idx_webhooks_org_active ON webhooks(org_id, active);

ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_isolation_webhooks ON webhooks
    USING (org_id = current_setting('app.current_org', TRUE)::UUID);
