#!/bin/sh
set -e

PSQL="psql postgresql://agr_svc_usr:gKHTwJOC7SbVHUQw1hLfUcjLaJtnZvYfR_M2hixl@postgres:5432/agr_platform"

echo "Running migrations..."
$PSQL -f /migrations/001_initial_schema.sql
echo "  001 done"
$PSQL -f /migrations/002_approval_enhancements.sql
echo "  002 done"
$PSQL -f /migrations/003_default_policy_trigger.sql
echo "  003 done"
$PSQL -f /migrations/004_agents_table.sql
echo "  004 done"
$PSQL -f /migrations/005_webhooks_table.sql
echo "  005 done"
$PSQL -f /migrations/006_audit_partitioning.sql
echo "  006 done"
$PSQL -f /migrations/007_pg_cron_audit_partitions.sql
echo "  007 done"
$PSQL -f /migrations/008_webhook_deliveries.sql
echo "  008 done"
$PSQL -f /migrations/009_agent_active.sql
echo "  009 done"
$PSQL -f /migrations/010_eval_week.sql
echo "  010 done"
$PSQL -f /migrations/011_indexes.sql
echo "  011 done"
$PSQL -f /migrations/012_token_version.sql
echo "  012 done"
$PSQL -f /migrations/013_status_check.sql
echo "  013 done"
$PSQL -f /migrations/014_audit_sequence_per_org.sql
echo "  014 done"
$PSQL -f /migrations/015_audit_agent_index.sql
echo "  015 done"
echo "All migrations complete."
