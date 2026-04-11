-- Rollback for migration 030: remove no_policy_action
ALTER TABLE organizations
  DROP CONSTRAINT IF EXISTS chk_no_policy_action;

ALTER TABLE organizations
  DROP COLUMN IF EXISTS no_policy_action;
