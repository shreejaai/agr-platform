-- Rollback 019: remove org role column
ALTER TABLE organizations DROP COLUMN IF EXISTS role;
