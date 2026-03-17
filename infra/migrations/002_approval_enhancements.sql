-- AGR Platform — Approval Enhancements
-- Adds approver_email (who to notify) and decision_at (when decided) to approval_requests

ALTER TABLE approval_requests
    ADD COLUMN approver_email TEXT,
    ADD COLUMN decision_at    TIMESTAMPTZ;
