-- Migration 024: org_members table
-- Supports team invite, role assignment, and access revocation.
-- Members are scoped to an org and tracked by email + role + status.
-- RLS is applied so each org can only see its own members.

CREATE TABLE IF NOT EXISTS org_members (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email       TEXT        NOT NULL,
    role        TEXT        NOT NULL DEFAULT 'viewer'
                                CHECK (role IN ('admin', 'operator', 'viewer')),
    status      TEXT        NOT NULL DEFAULT 'invited'
                                CHECK (status IN ('invited', 'active', 'revoked')),
    invited_by  TEXT,                       -- email or API key slug of inviter
    joined_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (org_id, email)
);

-- RLS: each org sees only its own members
ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_members_isolation ON org_members
    USING (org_id = current_setting('app.current_org_id', true)::uuid);

-- Index for fast lookup by org
CREATE INDEX IF NOT EXISTS idx_org_members_org_id ON org_members (org_id);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_org_members_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_org_members_updated_at
    BEFORE UPDATE ON org_members
    FOR EACH ROW EXECUTE FUNCTION update_org_members_updated_at();
