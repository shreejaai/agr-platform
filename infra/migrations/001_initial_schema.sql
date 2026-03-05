-- AGR Platform Initial Schema
-- PostgreSQL 16

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Organizations
CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE,
    plan        TEXT NOT NULL DEFAULT 'developer',
    api_key     TEXT UNIQUE NOT NULL,
    eval_count  BIGINT NOT NULL DEFAULT 0,
    eval_limit  BIGINT NOT NULL DEFAULT 10000,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_organizations_api_key ON organizations(api_key);

-- Policies
CREATE TABLE policies (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id  UUID,
    agent_id    TEXT,
    name        TEXT NOT NULL,
    level       TEXT NOT NULL,
    cedar_rule  TEXT NOT NULL,
    version     INT NOT NULL DEFAULT 1,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_policies_org_id ON policies(org_id);
CREATE INDEX idx_policies_org_active ON policies(org_id, active);

-- Approval Requests
CREATE TABLE approval_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL,
    action          TEXT NOT NULL,
    resource        TEXT NOT NULL,
    context         JSONB,
    status          TEXT NOT NULL DEFAULT 'pending',
    temporal_run_id TEXT,
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '48 hours',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_approval_requests_org_id ON approval_requests(org_id);
CREATE INDEX idx_approval_requests_status ON approval_requests(org_id, status);

-- Audit Events (append-only, hash-chained)
-- No FK to organizations intentionally — audit data outlives orgs
CREATE TABLE audit_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    sequence_num BIGSERIAL NOT NULL,
    event_type   TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    action       TEXT NOT NULL,
    resource     TEXT NOT NULL,
    decision     TEXT NOT NULL,
    policy_id    UUID,
    approval_id  UUID,
    payload      JSONB,
    prev_hash    TEXT,
    entry_hash   TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_events_org_id ON audit_events(org_id);
CREATE INDEX idx_audit_events_org_recorded ON audit_events(org_id, recorded_at);
CREATE INDEX idx_audit_events_org_type ON audit_events(org_id, event_type);

-- Row-Level Security
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation_organizations ON organizations
    USING (id = current_setting('app.current_org', TRUE)::UUID);
CREATE POLICY org_isolation_policies ON policies
    USING (org_id = current_setting('app.current_org', TRUE)::UUID);
CREATE POLICY org_isolation_approval_requests ON approval_requests
    USING (org_id = current_setting('app.current_org', TRUE)::UUID);
CREATE POLICY org_isolation_audit_events ON audit_events
    USING (org_id = current_setting('app.current_org', TRUE)::UUID);
