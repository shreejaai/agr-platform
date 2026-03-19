-- Rollback for 006_audit_partitioning.sql
-- Restores the unpartitioned audit_events table from the legacy backup.
-- WARNING: Events written after migration 006 will be in the partitioned table;
--          this restores only pre-migration data.

-- Move partitioned table out of the way
ALTER TABLE IF EXISTS audit_events RENAME TO audit_events_partitioned;

-- Restore original unpartitioned table
ALTER TABLE IF EXISTS audit_events_legacy RENAME TO audit_events;

-- Drop helper functions
DROP FUNCTION IF EXISTS create_audit_partition(int, int);
DROP FUNCTION IF EXISTS ensure_audit_partitions();
