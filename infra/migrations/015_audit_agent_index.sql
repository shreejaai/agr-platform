-- Migration 015: add composite index on audit_events(org_id, agent_id)
--
-- The GET /v1/audit endpoint filters by both org_id and agent_id when the
-- caller passes ?agent_id=... The existing idx_audit_org_time only covers
-- (org_id, recorded_at). Without this index, filtering by agent_id requires
-- a sequential scan of all events for that org.

CREATE INDEX IF NOT EXISTS idx_audit_events_org_agent
    ON audit_events(org_id, agent_id);
