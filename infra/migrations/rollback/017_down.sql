-- Rollback 017: remove policy lifecycle state column
DROP INDEX IF EXISTS idx_policies_org_state;
ALTER TABLE policies DROP COLUMN IF EXISTS state;
