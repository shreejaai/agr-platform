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

BEGIN;

-- Enable pg_cron if not already enabled
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Remove any existing schedule with this name (idempotent)
SELECT cron.unschedule('agr-audit-partitions')
WHERE EXISTS (
    SELECT 1 FROM cron.job WHERE jobname = 'agr-audit-partitions'
);

-- Schedule: 02:00 on the 1st of every month
-- ensure_audit_partitions() creates current month + 3 months ahead,
-- so the partitions are always ready before data arrives.
SELECT cron.schedule(
    'agr-audit-partitions',
    '0 2 1 * *',
    $$SELECT ensure_audit_partitions()$$
);

COMMIT;

-- Verify the job was registered:
-- SELECT jobid, jobname, schedule, command FROM cron.job WHERE jobname = 'agr-audit-partitions';
