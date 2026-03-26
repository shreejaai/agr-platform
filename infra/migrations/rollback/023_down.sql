-- Rollback 023: remove multi-step approval tables/columns
DROP TABLE IF EXISTS approval_steps;

ALTER TABLE approval_requests
    DROP COLUMN IF EXISTS quorum_type,
    DROP COLUMN IF EXISTS sla_hours,
    DROP COLUMN IF EXISTS escalation_email;
