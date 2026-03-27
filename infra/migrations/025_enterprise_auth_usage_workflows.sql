-- Migration 025: enterprise auth/session support, usage tracking, and workflow durability

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS eval_warning_threshold_pct INTEGER NOT NULL DEFAULT 80
        CHECK (eval_warning_threshold_pct >= 1 AND eval_warning_threshold_pct <= 100),
    ADD COLUMN IF NOT EXISTS eval_soft_limit_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS usage_soft_limit_warning_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS usage_last_warned_count BIGINT,
    ADD COLUMN IF NOT EXISTS sso_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS sso_provider TEXT,
    ADD COLUMN IF NOT EXISTS sso_metadata_url TEXT,
    ADD COLUMN IF NOT EXISTS sso_metadata_xml TEXT,
    ADD COLUMN IF NOT EXISTS sso_entity_id TEXT,
    ADD COLUMN IF NOT EXISTS sso_domains TEXT,
    ADD COLUMN IF NOT EXISTS sso_default_role TEXT NOT NULL DEFAULT 'viewer'
        CHECK (sso_default_role IN ('admin', 'operator', 'viewer')),
    ADD COLUMN IF NOT EXISTS sso_auto_join BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS workflow_status TEXT NOT NULL DEFAULT 'running'
        CHECK (workflow_status IN ('running', 'completed', 'failed', 'escalated')),
    ADD COLUMN IF NOT EXISTS workflow_last_error TEXT,
    ADD COLUMN IF NOT EXISTS workflow_last_transition_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS workflow_fallback_mode TEXT NOT NULL DEFAULT 'none'
        CHECK (
            workflow_fallback_mode IN (
                'none',
                'db_only_temporal_unavailable',
                'db_only_start_failed',
                'signal_retry_exhausted',
                'timeout_enforced'
            )
        ),
    ADD COLUMN IF NOT EXISTS workflow_escalated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_approval_requests_workflow_status
    ON approval_requests (org_id, workflow_status, created_at DESC);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token           TEXT NOT NULL UNIQUE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    identity_sub    TEXT NOT NULL,
    identity_email  TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer'
                        CHECK (role IN ('admin', 'operator', 'viewer')),
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_org_expires
    ON auth_sessions (org_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_usage (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_id            TEXT NOT NULL,
    total_evaluations   BIGINT NOT NULL DEFAULT 0,
    last_evaluated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_evaluation_usage_org_total
    ON evaluation_usage (org_id, total_evaluations DESC, agent_id);

CREATE OR REPLACE FUNCTION update_evaluation_usage_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_evaluation_usage_updated_at ON evaluation_usage;
CREATE TRIGGER trg_evaluation_usage_updated_at
    BEFORE UPDATE ON evaluation_usage
    FOR EACH ROW EXECUTE FUNCTION update_evaluation_usage_updated_at();
