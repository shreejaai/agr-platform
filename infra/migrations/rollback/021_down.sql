-- Rollback 021: remove agent capabilities column
ALTER TABLE agents DROP COLUMN IF EXISTS capabilities;
