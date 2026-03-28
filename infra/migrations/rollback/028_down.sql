-- Rollback migration 028

ALTER TABLE webhooks
    DROP COLUMN IF EXISTS rotating_secret_expires_at,
    DROP COLUMN IF EXISTS rotating_secret;
