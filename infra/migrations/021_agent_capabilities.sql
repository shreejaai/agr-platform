-- Migration 021: agent capabilities
-- Adds a JSONB array of capability strings to each agent record.
-- Example: ["read_files", "write_db", "call_api"]

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '[]';
