-- Migration 013: add CHECK constraint to approval_requests.status
-- Prevents any value outside the known state machine from being written
-- at the DB level, giving an extra layer of protection beyond app validation.

ALTER TABLE approval_requests
    ADD CONSTRAINT approval_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'escalated'));
