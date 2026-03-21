-- Rollback 011: drop performance indexes
DROP INDEX IF EXISTS idx_audit_org_time;
DROP INDEX IF EXISTS idx_approvals_org_status;
DROP INDEX IF EXISTS idx_delivery_webhook_time;
