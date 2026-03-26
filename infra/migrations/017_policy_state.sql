-- Migration 017: policy lifecycle states
-- Adds a `state` column to policies with three values: draft, active, archived.
--
-- draft    → created but not yet evaluated; invisible to the Cedar engine
-- active   → evaluated on every POST /v1/evaluate (was: active=true)
-- archived → soft-deleted; preserved for audit FK integrity (was: active=false)
--
-- The existing `active` boolean is kept and kept in sync for backward compat:
--   state='active'   ↔  active=TRUE
--   state='draft'    ↔  active=FALSE
--   state='archived' ↔  active=FALSE

ALTER TABLE policies
    ADD COLUMN state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('draft', 'active', 'archived'));

-- Back-fill: rows already soft-deleted (active=false) become archived.
-- All other rows default to 'active' from the column default above.
UPDATE policies SET state = 'archived' WHERE active = FALSE;

CREATE INDEX idx_policies_org_state
    ON policies(org_id, state);
