-- Migration 012: add token_version to approval_requests
-- Incremented on every escalation so stale email/Slack links are immediately
-- invalidated when the approval is re-routed to a different approver (H3).

ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
