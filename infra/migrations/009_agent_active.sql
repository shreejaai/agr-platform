-- Migration 009: add active column to agents table
ALTER TABLE agents ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
