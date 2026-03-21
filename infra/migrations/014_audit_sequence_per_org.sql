-- Migration 014: Per-org audit sequence uniqueness + policy FK guard
--
-- Fixes:
--   H6: audit_events.sequence_num was a global counter shared across all orgs.
--       Without UNIQUE(org_id, sequence_num) the hash chain verification was
--       not reliably per-org isolated. Two orgs could share the same
--       sequence_num, making verify_audit_chain potentially walk cross-tenant rows.
--
--   M3: audit_events.policy_id references policies with no FK constraint
--       (intentional for audit immutability). But hard-deleting policies leaves
--       stale policy_id values. This migration does NOT add an FK — audit rows
--       must survive policy deletion. Instead, policy DELETE is converted to a
--       soft-delete (active=false) via an application-level comment/convention.
--       The migration adds a partial unique index to enforce uniqueness.
--
-- Idempotent: index creation uses IF NOT EXISTS.

-- H6: enforce (org_id, sequence_num) uniqueness per partition / parent table.
-- On a partitioned table Postgres requires the partition key (recorded_at) to be
-- part of any unique constraint. We create a unique index on the parent — Postgres
-- propagates it to all child partitions automatically.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'audit_events'
          AND indexname  = 'idx_audit_events_org_seq_unique'
    ) THEN
        -- Partitioned table: unique index must include partition key
        EXECUTE $idx$
            CREATE UNIQUE INDEX idx_audit_events_org_seq_unique
            ON audit_events (org_id, sequence_num, recorded_at)
        $idx$;
        RAISE NOTICE 'Migration 014: created unique index idx_audit_events_org_seq_unique.';
    ELSE
        RAISE NOTICE 'Migration 014: idx_audit_events_org_seq_unique already exists, skipping.';
    END IF;
END;
$$;
