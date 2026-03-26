-- Migration 018: policy version history
-- Stores immutable snapshots of policy state taken before each content-changing PATCH.
-- Enables GET /v1/policies/{id}/versions (history) and
-- POST /v1/policies/{id}/rollback/{version} (restore).
--
-- policy_id references policies(id) with CASCADE so snapshots are cleaned up
-- if a policy is ever hard-deleted (currently policies are only soft-archived,
-- but the FK is defensive).

CREATE TABLE policy_versions (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id   UUID    NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    org_id      UUID    NOT NULL,
    cedar_rule  TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    level       TEXT    NOT NULL,
    state       TEXT    NOT NULL,
    version     INT     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary access pattern: list versions for a policy newest-first
CREATE INDEX idx_policy_versions_policy
    ON policy_versions(policy_id, version DESC);

-- Secondary access pattern: org-scoped queries without a policy_id join
CREATE INDEX idx_policy_versions_org
    ON policy_versions(org_id);
