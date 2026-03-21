-- Rollback 012: remove token_version from approval_requests
ALTER TABLE approval_requests DROP COLUMN IF EXISTS token_version;
