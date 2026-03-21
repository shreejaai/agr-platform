-- Rollback 009: remove active column from agents
ALTER TABLE agents DROP COLUMN IF EXISTS active;
