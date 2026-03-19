-- 008_webhook_deliveries.sql
-- Dead-letter queue for webhook deliveries.
-- Every delivery attempt (success or failure) is recorded here.
-- Failed deliveries can be replayed via POST /v1/webhooks/{id}/deliveries/{id}/retry.

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id  UUID        NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    org_id      UUID        NOT NULL,
    event       TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}',
    status      TEXT        NOT NULL DEFAULT 'pending',  -- pending | delivered | failed
    http_status INTEGER,
    attempts    INTEGER     NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook_id
    ON webhook_deliveries(webhook_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_org_id
    ON webhook_deliveries(org_id, created_at DESC);

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'webhook_deliveries' AND policyname = 'webhook_deliveries_org_isolation'
    ) THEN
        CREATE POLICY webhook_deliveries_org_isolation ON webhook_deliveries
            USING (org_id::text = current_setting('app.current_org', true));
    END IF;
END $$;
