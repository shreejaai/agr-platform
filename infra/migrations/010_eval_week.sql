-- Migration 010: add eval_week_start column; set developer plan limit to 100/week
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS eval_week_start TIMESTAMPTZ;

-- Update existing developer orgs to the new 100/week limit
UPDATE organizations SET eval_limit = 100 WHERE plan = 'developer' AND eval_limit = 10000;
