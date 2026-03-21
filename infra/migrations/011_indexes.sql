-- Migration 011: add missing indexes for production query performance

-- H1: audit_events — org + time filter (GET /v1/audit, GET /v1/audit/verify)
CREATE INDEX IF NOT EXISTS idx_audit_org_time
    ON audit_events(org_id, recorded_at DESC);

-- H2: approval_requests — org + status filter (GET /v1/approvals?status=pending)
CREATE INDEX IF NOT EXISTS idx_approvals_org_status
    ON approval_requests(org_id, status);

-- H3: webhook_deliveries — webhook + time (GET /v1/webhooks/{id}/deliveries)
CREATE INDEX IF NOT EXISTS idx_delivery_webhook_time
    ON webhook_deliveries(webhook_id, created_at DESC);
