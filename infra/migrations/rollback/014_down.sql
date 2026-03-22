-- Rollback migration 014: Remove unique index on audit_events(org_id, sequence_num, recorded_at)
-- Safe to run: dropping an index does not affect data

DROP INDEX IF EXISTS idx_audit_events_org_seq_unique;
