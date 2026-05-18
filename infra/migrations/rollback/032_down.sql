-- Rollback for migration 032: audit_export_jobs

DROP POLICY IF EXISTS audit_export_jobs_isolation ON audit_export_jobs;
DROP INDEX IF EXISTS audit_export_jobs_status_idx;
DROP INDEX IF EXISTS audit_export_jobs_org_started_idx;
DROP TABLE IF EXISTS audit_export_jobs;
