-- Migration 019: org RBAC roles
-- Adds a `role` column to organizations.  The role governs what the API key
-- bearer is permitted to do: admin (full), operator (create/update), viewer (read-only).
-- Existing orgs default to 'admin' to preserve current behavior.

ALTER TABLE organizations
    ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'
        CHECK (role IN ('admin', 'operator', 'viewer'));
