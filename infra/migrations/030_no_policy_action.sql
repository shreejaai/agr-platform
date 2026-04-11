-- Migration 030: org-level configurable fallback when no policy matches
--
-- Adds no_policy_action to organizations so each org can control what
-- happens when /v1/evaluate finds no active policy for the request.
--
-- Values: deny (safe default) | allow | approval_required
-- Existing orgs default to 'deny' — no behaviour change on upgrade.

ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS no_policy_action TEXT NOT NULL DEFAULT 'deny';

-- Guard: only valid values permitted (enforce at DB level too)
ALTER TABLE organizations
  ADD CONSTRAINT chk_no_policy_action
    CHECK (no_policy_action IN ('deny', 'allow', 'approval_required'));
