-- Rollback 020: remove agent profile columns
ALTER TABLE agents
    DROP COLUMN IF EXISTS name,
    DROP COLUMN IF EXISTS owner,
    DROP COLUMN IF EXISTS framework,
    DROP COLUMN IF EXISTS environment,
    DROP COLUMN IF EXISTS trust_level;
