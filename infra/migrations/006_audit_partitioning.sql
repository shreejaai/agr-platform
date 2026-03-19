-- Migration 006: Convert audit_events to monthly range-partitioned table
--
-- Strategy:
--   1. Rename existing table to audit_events_legacy
--   2. Create new partitioned table with identical schema
--   3. Re-apply RLS
--   4. Create helper functions for partition management
--   5. Pre-create partitions for current month + 12 months ahead
--   6. Copy existing data from legacy table into partitioned table
--
-- Idempotent: detects whether audit_events is already partitioned and skips
-- the structural steps if so (safe to re-run with `for f in migrations/*.sql`).

BEGIN;

DO $$
BEGIN

-- ────────────────────────────────────────────────────────────
-- Idempotency guard
-- If audit_events is already a partitioned table (relkind = 'p')
-- the structural steps have already been applied — skip them.
-- ────────────────────────────────────────────────────────────
IF EXISTS (
    SELECT 1 FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = 'audit_events'
      AND c.relkind = 'p'
      AND n.nspname = current_schema()
) THEN
    RAISE NOTICE 'Migration 006 already applied (audit_events is already partitioned). Skipping structural steps.';

ELSE

    -- ────────────────────────────────────────────────────────────
    -- 1. Rename legacy table (keeps data safe during migration)
    -- ────────────────────────────────────────────────────────────
    EXECUTE 'ALTER TABLE audit_events RENAME TO audit_events_legacy';

    -- Rename old indexes so they don't conflict with the new table's names.
    -- Use WHEN OTHERS to handle any naming variant gracefully.
    BEGIN EXECUTE 'ALTER INDEX idx_audit_events_org_id       RENAME TO idx_audit_legacy_org_id';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN EXECUTE 'ALTER INDEX idx_audit_events_org_recorded  RENAME TO idx_audit_legacy_org_recorded';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN EXECUTE 'ALTER INDEX idx_audit_events_org_type      RENAME TO idx_audit_legacy_org_type';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    -- also handle older naming variants
    BEGIN EXECUTE 'ALTER INDEX idx_audit_org_id      RENAME TO idx_audit_legacy_org_id';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN EXECUTE 'ALTER INDEX idx_audit_agent_id    RENAME TO idx_audit_legacy_agent_id';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN EXECUTE 'ALTER INDEX idx_audit_event_type  RENAME TO idx_audit_legacy_event_type';
    EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN EXECUTE 'ALTER INDEX idx_audit_recorded_at RENAME TO idx_audit_legacy_recorded_at';
    EXCEPTION WHEN OTHERS THEN NULL; END;

    -- ────────────────────────────────────────────────────────────
    -- 2. Create the new partitioned parent table
    --    Schema matches models.py AuditEvent exactly.
    -- ────────────────────────────────────────────────────────────
    EXECUTE '
        CREATE TABLE audit_events (
            id              UUID        NOT NULL DEFAULT gen_random_uuid(),
            org_id          UUID        NOT NULL,
            sequence_num    BIGINT      NOT NULL DEFAULT 0,
            event_type      TEXT        NOT NULL,
            agent_id        TEXT        NOT NULL,
            action          TEXT        NOT NULL,
            resource        TEXT        NOT NULL,
            decision        TEXT        NOT NULL,
            policy_id       UUID,
            approval_id     UUID,
            payload         JSONB,
            prev_hash       TEXT,
            entry_hash      TEXT        NOT NULL DEFAULT '''',
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    ';

    -- ────────────────────────────────────────────────────────────
    -- 3. Row-Level Security (inherited by child partitions)
    -- ────────────────────────────────────────────────────────────
    EXECUTE 'ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY';

    EXECUTE $pol$
        CREATE POLICY audit_events_org_isolation ON audit_events
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
    $pol$;

    -- ────────────────────────────────────────────────────────────
    -- 6. Migrate existing data from legacy table
    -- ────────────────────────────────────────────────────────────
    EXECUTE '
        INSERT INTO audit_events
            (id, org_id, sequence_num, event_type, agent_id, action, resource, decision,
             policy_id, approval_id, payload, prev_hash, entry_hash, recorded_at)
        SELECT
            id, org_id, sequence_num, event_type, agent_id, action, resource, decision,
            policy_id, approval_id, payload, prev_hash, entry_hash, recorded_at
        FROM audit_events_legacy
    ';

    RAISE NOTICE 'Migration 006 structural steps complete.';

END IF; -- end idempotency guard

END;
$$;


-- ────────────────────────────────────────────────────────────
-- 4. Partition management helper functions
--    CREATE OR REPLACE is always idempotent — run unconditionally.
-- ────────────────────────────────────────────────────────────

-- create_audit_partition(year, month)
--   Creates a monthly child partition if it does not already exist.
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

        EXECUTE format('CREATE INDEX ON %I (org_id)',      tbl_name);
        EXECUTE format('CREATE INDEX ON %I (agent_id)',    tbl_name);
        EXECUTE format('CREATE INDEX ON %I (event_type)',  tbl_name);
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
--    create_audit_partition() is idempotent — safe to re-run.
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
-- 7. Optional: keep legacy table for rollback safety.
--    Drop it after verifying counts in production:
--
--      SELECT count(*) FROM audit_events;
--      SELECT count(*) FROM audit_events_legacy;
--      DROP TABLE audit_events_legacy;
-- ────────────────────────────────────────────────────────────

COMMIT;
