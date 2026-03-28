-- Migration 029: reusable policy test suites

CREATE TABLE IF NOT EXISTS policy_test_suites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    test_cases JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE policy_test_suites ENABLE ROW LEVEL SECURITY;

CREATE POLICY policy_test_suites_isolation ON policy_test_suites
    USING (org_id::text = current_setting('app.current_org_id', true));
