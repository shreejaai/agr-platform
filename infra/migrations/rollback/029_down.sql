-- Rollback migration 029

DROP POLICY IF EXISTS policy_test_suites_isolation ON policy_test_suites;
DROP TABLE IF EXISTS policy_test_suites;
