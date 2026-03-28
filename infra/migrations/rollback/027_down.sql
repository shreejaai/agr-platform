-- Rollback migration 027

DROP POLICY IF EXISTS api_keys_isolation ON api_keys;
DROP TABLE IF EXISTS api_keys;
