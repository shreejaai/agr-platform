-- Rollback migration 025

DROP TRIGGER IF EXISTS trg_evaluation_usage_updated_at ON evaluation_usage;
DROP FUNCTION IF EXISTS update_evaluation_usage_updated_at();

DROP TABLE IF EXISTS evaluation_usage;
DROP TABLE IF EXISTS auth_sessions;

DROP INDEX IF EXISTS idx_approval_requests_workflow_status;

ALTER TABLE approval_requests
    DROP COLUMN IF EXISTS workflow_escalated_at,
    DROP COLUMN IF EXISTS workflow_fallback_mode,
    DROP COLUMN IF EXISTS workflow_last_transition_at,
    DROP COLUMN IF EXISTS workflow_last_error,
    DROP COLUMN IF EXISTS workflow_status;

ALTER TABLE organizations
    DROP COLUMN IF EXISTS sso_auto_join,
    DROP COLUMN IF EXISTS sso_default_role,
    DROP COLUMN IF EXISTS sso_domains,
    DROP COLUMN IF EXISTS sso_entity_id,
    DROP COLUMN IF EXISTS sso_metadata_xml,
    DROP COLUMN IF EXISTS sso_metadata_url,
    DROP COLUMN IF EXISTS sso_provider,
    DROP COLUMN IF EXISTS sso_enabled,
    DROP COLUMN IF EXISTS usage_last_warned_count,
    DROP COLUMN IF EXISTS usage_soft_limit_warning_sent_at,
    DROP COLUMN IF EXISTS eval_soft_limit_enabled,
    DROP COLUMN IF EXISTS eval_warning_threshold_pct;
