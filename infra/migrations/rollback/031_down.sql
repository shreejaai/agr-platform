-- Rollback for migration 031.

ALTER TABLE approval_requests
  DROP COLUMN IF EXISTS reminder_sent_at;
