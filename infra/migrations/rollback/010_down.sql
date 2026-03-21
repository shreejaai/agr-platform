-- Rollback 010: remove eval_week_start; restore developer limit to 10000
ALTER TABLE organizations DROP COLUMN IF EXISTS eval_week_start;
UPDATE organizations SET eval_limit = 10000 WHERE plan = 'developer' AND eval_limit = 100;
