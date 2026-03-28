-- Rollback migration 026

DROP POLICY IF EXISTS org_compliance_configs_isolation ON org_compliance_configs;
DROP TABLE IF EXISTS org_compliance_configs;
