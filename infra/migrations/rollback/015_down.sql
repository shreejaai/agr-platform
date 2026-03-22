-- Rollback migration 015: Remove index on audit_events(org_id, agent_id)
-- Safe to run: dropping an index does not affect data

DROP INDEX IF EXISTS idx_audit_events_org_agent;
