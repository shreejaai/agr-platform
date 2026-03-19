-- Rollback for 003_default_policy_trigger.sql

DROP TRIGGER IF EXISTS on_org_created ON organizations;
DROP FUNCTION IF EXISTS seed_default_policies();
