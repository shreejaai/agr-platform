-- Migration 023: multi-step approval support
-- Adds quorum_type, sla_hours, escalation_email to approval_requests.
-- Creates approval_steps table for tracking individual approver decisions.

ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS quorum_type TEXT NOT NULL DEFAULT 'any'
        CHECK (quorum_type IN ('any', 'all')),
    ADD COLUMN IF NOT EXISTS sla_hours INT,
    ADD COLUMN IF NOT EXISTS escalation_email TEXT;

CREATE TABLE IF NOT EXISTS approval_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id     UUID NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL,
    approver_email  TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approval_steps_approval_id ON approval_steps(approval_id);

ALTER TABLE approval_steps ENABLE ROW LEVEL SECURITY;

CREATE POLICY approval_steps_isolation ON approval_steps
    USING (org_id::text = current_setting('app.current_org_id', true));
