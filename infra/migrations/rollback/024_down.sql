-- Rollback migration 024: drop org_members table
DROP TRIGGER IF EXISTS trg_org_members_updated_at ON org_members;
DROP FUNCTION IF EXISTS update_org_members_updated_at();
DROP TABLE IF EXISTS org_members;
