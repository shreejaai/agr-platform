-- Rollback for 001_initial_schema.sql
-- WARNING: This drops all AGR tables and their data. Use only in dev/test.

DROP TABLE IF EXISTS audit_events CASCADE;
DROP TABLE IF EXISTS approval_requests CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;
