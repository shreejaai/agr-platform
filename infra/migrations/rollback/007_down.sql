-- Rollback for 007_pg_cron_audit_partitions.sql

SELECT cron.unschedule('agr-audit-partitions');
