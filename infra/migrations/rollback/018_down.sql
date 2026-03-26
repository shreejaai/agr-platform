-- Rollback 018: drop policy version history table
DROP INDEX IF EXISTS idx_policy_versions_org;
DROP INDEX IF EXISTS idx_policy_versions_policy;
DROP TABLE IF EXISTS policy_versions;
