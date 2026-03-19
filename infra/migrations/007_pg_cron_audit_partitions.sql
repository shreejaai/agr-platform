-- Migration 007: Schedule monthly audit partition creation via pg_cron
--
-- Prerequisites:
--   1. pg_cron extension must be enabled in postgresql.conf:
--        shared_preload_libraries = 'pg_cron'
--        cron.database_name = 'agr_dev'   # or your DB name
--   2. Must be run as a superuser (pg_cron requires superuser for scheduling).
--
-- On Railway (managed PostgreSQL) or Supabase, pg_cron is available.
-- On vanilla RDS, enable via: CREATE EXTENSION pg_cron;
--
-- The ensure_audit_partitions() function was created in migration 006.
-- It creates partitions for the current month + 3 months ahead (idempotent).
--
-- Running this migration is OPTIONAL if you manage partitions manually or
-- pre-created enough months in migration 006 (which covers 13 months ahead).

-- Wrapped in a DO block so the migration succeeds even when pg_cron
-- is not installed (local Docker, vanilla RDS without the extension).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;

    -- Remove any existing schedule (idempotent)
    IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'agr-audit-partitions') THEN
        PERFORM cron.unschedule('agr-audit-partitions');
    END IF;

    -- Schedule: 02:00 on the 1st of every month
    PERFORM cron.schedule(
        'agr-audit-partitions',
        '0 2 1 * *',
        'SELECT ensure_audit_partitions()'
    );

    RAISE NOTICE 'pg_cron job scheduled: agr-audit-partitions (0 2 1 * *)';

EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_cron not available (%). Skipping automated partition scheduling. '
                 'Migration 006 pre-creates 13 months of partitions. '
                 'Re-run this migration on a pg_cron-enabled host (Railway, Supabase, RDS) when ready.',
                 SQLERRM;
END;
$$;

-- Verify the job was registered:
-- SELECT jobid, jobname, schedule, command FROM cron.job WHERE jobname = 'agr-audit-partitions';
