-- Migration 006: Convert audit_events to monthly range-partitioned table
--
-- Strategy:
--   1. Rename existing table to audit_events_legacy
--   2. Create new partitioned table with identical schema
--   3. Re-apply RLS
--   4. Create helper functions for partition management
--   5. Pre-create partitions for current month + 12 months ahead
--   6. Copy existing data from legacy table into partitioned table
--   7. Swap views so callers continue using audit_events
--
-- Run with superuser or a role that has CREATE privilege on the schema.

BEGIN;

-- ────────────────────────────────────────────────────────────
-- 1. Rename legacy table (keeps data safe during migration)
-- ────────────────────────────────────────────────────────────
ALTER TABLE audit_events RENAME TO audit_events_legacy;

-- Drop the old indexes so they don't conflict with the new table's names
ALTER INDEX IF EXISTS idx_audit_org_id RENAME TO idx_audit_legacy_org_id;
ALTER INDEX IF EXISTS idx_audit_agent_id RENAME TO idx_audit_legacy_agent_id;
ALTER INDEX IF EXISTS idx_audit_event_type RENAME TO idx_audit_legacy_event_type;
ALTER INDEX IF EXISTS idx_audit_recorded_at RENAME TO idx_audit_legacy_recorded_at;


-- ────────────────────────────────────────────────────────────
-- 2. Create the new partitioned parent table
-- ────────────────────────────────────────────────────────────
CREATE TABLE audit_events (
    id              UUID        NOT NULL DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL,
    event_type      TEXT        NOT NULL,
    agent_id        TEXT,
    action          TEXT,
    resource        TEXT,
    decision        TEXT,
    approval_id     UUID,
    payload         JSONB,
    sequence_num    BIGINT      NOT NULL DEFAULT 0,
    prev_hash       TEXT,
    event_hash      TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, recorded_at)   -- partition key must be in PK
) PARTITION BY RANGE (recorded_at);


-- ────────────────────────────────────────────────────────────
-- 3. Row-Level Security on the partitioned table
--    (RLS is inherited by child partitions automatically)
-- ────────────────────────────────────────────────────────────
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_events_org_isolation ON audit_events
    USING (org_id = current_setting('app.current_org_id', true)::uuid);


-- ────────────────────────────────────────────────────────────
-- 4. Partition management helper functions
-- ────────────────────────────────────────────────────────────

-- create_audit_partition(year, month)
--   Creates a monthly child partition if it does not already exist.
--   Returns the partition table name.
CREATE OR REPLACE FUNCTION create_audit_partition(p_year INT, p_month INT)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    tbl_name  TEXT;
    start_dt  DATE;
    end_dt    DATE;
BEGIN
    tbl_name := format('audit_events_%s_%s', p_year, lpad(p_month::text, 2, '0'));
    start_dt := make_date(p_year, p_month, 1);
    end_dt   := start_dt + INTERVAL '1 month';

    -- Idempotent: skip if already exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = tbl_name AND n.nspname = current_schema()
    ) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF audit_events
             FOR VALUES FROM (%L) TO (%L)',
            tbl_name, start_dt, end_dt
        );

        -- Indexes on each partition (localised — faster than global indexes)
        EXECUTE format('CREATE INDEX ON %I (org_id)', tbl_name);
        EXECUTE format('CREATE INDEX ON %I (agent_id)', tbl_name);
        EXECUTE format('CREATE INDEX ON %I (event_type)', tbl_name);
        EXECUTE format('CREATE INDEX ON %I (recorded_at)', tbl_name);

        RAISE NOTICE 'Created partition % (% to %)', tbl_name, start_dt, end_dt;
    ELSE
        RAISE NOTICE 'Partition % already exists, skipping', tbl_name;
    END IF;

    RETURN tbl_name;
END;
$$;


-- ensure_audit_partitions()
--   Call from a scheduled job (e.g. pg_cron monthly).
--   Creates the current month's partition + 3 months ahead.
CREATE OR REPLACE FUNCTION ensure_audit_partitions()
RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE
    d DATE;
BEGIN
    FOR i IN 0..3 LOOP
        d := date_trunc('month', now()) + (i || ' months')::INTERVAL;
        PERFORM create_audit_partition(EXTRACT(YEAR FROM d)::INT, EXTRACT(MONTH FROM d)::INT);
    END LOOP;
END;
$$;


-- ────────────────────────────────────────────────────────────
-- 5. Pre-create partitions: current month + 12 months ahead
-- ────────────────────────────────────────────────────────────
DO $$
DECLARE
    d DATE;
BEGIN
    FOR i IN 0..12 LOOP
        d := date_trunc('month', now()) + (i || ' months')::INTERVAL;
        PERFORM create_audit_partition(EXTRACT(YEAR FROM d)::INT, EXTRACT(MONTH FROM d)::INT);
    END LOOP;
END;
$$;


-- ────────────────────────────────────────────────────────────
-- 6. Migrate existing data from legacy table
-- ────────────────────────────────────────────────────────────
INSERT INTO audit_events
SELECT * FROM audit_events_legacy;

-- ────────────────────────────────────────────────────────────
-- 7. Optional: keep legacy table for rollback safety.
--    Drop it after verifying counts in production:
--
--      SELECT count(*) FROM audit_events;
--      SELECT count(*) FROM audit_events_legacy;
--      DROP TABLE audit_events_legacy;
-- ────────────────────────────────────────────────────────────

COMMIT;
