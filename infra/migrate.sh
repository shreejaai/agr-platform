#!/bin/sh
set -e

PSQL="psql postgresql://${POSTGRES_USER:-agr_svc_usr}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-agr_platform}"

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
$PSQL -f /migrations/016_copilot_history.sql
echo "  016 done"
$PSQL -f /migrations/017_policy_state.sql
echo "  017 done"
$PSQL -f /migrations/018_policy_versions.sql
echo "  018 done"
$PSQL -f /migrations/019_org_roles.sql
echo "  019 done"
$PSQL -f /migrations/020_agent_profile.sql
echo "  020 done"
$PSQL -f /migrations/021_agent_capabilities.sql
echo "  021 done"
$PSQL -f /migrations/022_org_risk_config.sql
echo "  022 done"
$PSQL -f /migrations/023_approval_steps.sql
echo "  023 done"
$PSQL -f /migrations/024_org_members.sql
echo "  024 done"
$PSQL -f /migrations/025_enterprise_auth_usage_workflows.sql
echo "  025 done"
$PSQL -f /migrations/026_compliance_enforcement.sql
echo "  026 done"
$PSQL -f /migrations/027_api_key_scopes.sql
echo "  027 done"
$PSQL -f /migrations/028_webhook_secret_rotation.sql
echo "  028 done"
$PSQL -f /migrations/029_policy_test_suites.sql
echo "  029 done"
$PSQL -f /migrations/030_no_policy_action.sql
echo "  030 done"
$PSQL -f /migrations/031_approval_reminder_audit.sql
echo "  031 done"
$PSQL -f /migrations/032_audit_export_jobs.sql
echo "  032 done"
echo "All migrations complete."
