-- Migration 028: webhook secret rotation grace window

ALTER TABLE webhooks
    ADD COLUMN IF NOT EXISTS rotating_secret VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS rotating_secret_expires_at TIMESTAMPTZ NULL;
