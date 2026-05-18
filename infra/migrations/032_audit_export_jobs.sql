-- Migration 032: durable audit export jobs
-- Replaces the in-memory _EXPORT_JOBS dict so exports survive process restarts.

CREATE TABLE IF NOT EXISTS audit_export_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'ready', 'failed')),
    format TEXT NOT NULL CHECK (format IN ('json', 'csv')),
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    file_path TEXT NULL,
    error TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS audit_export_jobs_org_started_idx
    ON audit_export_jobs (org_id, started_at DESC);

CREATE INDEX IF NOT EXISTS audit_export_jobs_status_idx
    ON audit_export_jobs (status)
    WHERE status = 'pending';

ALTER TABLE audit_export_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_export_jobs_isolation ON audit_export_jobs
    USING (org_id::text = current_setting('app.current_org_id', true));
