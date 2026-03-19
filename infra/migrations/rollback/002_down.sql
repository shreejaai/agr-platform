-- Rollback for 002_approval_enhancements.sql

ALTER TABLE approval_requests
  DROP COLUMN IF EXISTS approver_email,
  DROP COLUMN IF EXISTS decision_at,
  DROP COLUMN IF EXISTS temporal_run_id;
