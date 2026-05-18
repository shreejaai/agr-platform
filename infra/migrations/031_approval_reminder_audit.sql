-- Migration 031: track approval reminder dispatch for idempotency
--
-- Adds reminder_sent_at to approval_requests so the Temporal reminder
-- activity can no-op if it has already fired for an approval (durable
-- guard against double-send on worker restarts / workflow replays).

ALTER TABLE approval_requests
  ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ NULL;
