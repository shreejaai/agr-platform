-- Migration 004: Agent registration persistence

CREATE TABLE agents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_id    TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, agent_id)
);

CREATE INDEX idx_agents_org_id ON agents(org_id);

-- RLS: agents are org-scoped
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_isolation_agents ON agents
    USING (org_id = current_setting('app.current_org', TRUE)::UUID);
