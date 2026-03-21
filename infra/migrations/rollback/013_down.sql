-- Rollback 013: drop status CHECK constraint
ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS approval_status_check;
