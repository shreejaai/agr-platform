#!/bin/sh
set -e

PSQL="psql postgresql://agr:password@postgres:5432/agr_dev"

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
$PSQL -f /migrations/008_webhook_deliveries.sql
echo "  008 done"
$PSQL -f /migrations/009_agent_active.sql
echo "  009 done"
echo "All migrations complete."
