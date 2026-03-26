-- Migration 020: agent profile columns
-- Adds typed profile fields to agents table.
-- trust_level governs risk scoring (replaces name-prefix heuristic).
-- Existing rows default to 'unknown' trust_level.

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS name TEXT,
    ADD COLUMN IF NOT EXISTS owner TEXT,
    ADD COLUMN IF NOT EXISTS framework TEXT,
    ADD COLUMN IF NOT EXISTS environment TEXT,
    ADD COLUMN IF NOT EXISTS trust_level TEXT NOT NULL DEFAULT 'unknown'
        CHECK (trust_level IN ('trusted', 'verified', 'unknown', 'untrusted'));
