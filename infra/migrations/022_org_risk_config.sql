-- Migration 022: per-org risk scoring configuration
-- Allows enterprise customers to tune risk weights and decision thresholds
-- without a code deploy. One row per org (UNIQUE on org_id).

CREATE TABLE IF NOT EXISTS org_risk_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Factor weights (must sum to 1.0 — enforced in application layer)
    weight_action_severity      FLOAT NOT NULL DEFAULT 0.30,
    weight_context_signals      FLOAT NOT NULL DEFAULT 0.20,
    weight_rate_pattern         FLOAT NOT NULL DEFAULT 0.15,
    weight_agent_trust          FLOAT NOT NULL DEFAULT 0.15,
    weight_amount_scale         FLOAT NOT NULL DEFAULT 0.10,
    weight_resource_sensitivity FLOAT NOT NULL DEFAULT 0.10,

    -- Decision thresholds
    threshold_allow_max     INT NOT NULL DEFAULT 30,
    threshold_approval_max  INT NOT NULL DEFAULT 70,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (org_id)
);

ALTER TABLE org_risk_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_risk_configs_isolation ON org_risk_configs
    USING (org_id::text = current_setting('app.current_org_id', true));
