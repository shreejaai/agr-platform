-- Migration 003: Seed default Cedar policies for every new organization
-- Mirrors the 5 policies in packages/agr-core/policies/default.cedar

CREATE OR REPLACE FUNCTION seed_default_policies()
RETURNS TRIGGER AS $fn$
BEGIN
    INSERT INTO policies (id, org_id, name, level, cedar_rule, active) VALUES
    (
        gen_random_uuid(), NEW.id,
        'Block production DB drops', 'org',
        $rule$forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)
when { resource has environment && resource.environment == "production" };$rule$,
        TRUE
    ),
    (
        gen_random_uuid(), NEW.id,
        'Require approval for production deploys', 'org',
        $rule$forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" }
unless { context has approval_status && context.approval_status == "approved" };$rule$,
        TRUE
    ),
    (
        gen_random_uuid(), NEW.id,
        'Block writes to secrets/env files', 'org',
        $rule$forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)
when { resource has path && (resource.path like "*.env*" || resource.path like "*secrets*") };$rule$,
        TRUE
    ),
    (
        gen_random_uuid(), NEW.id,
        'Allow staging auto-deploy', 'org',
        $rule$permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };$rule$,
        TRUE
    ),
    (
        gen_random_uuid(), NEW.id,
        'Allow source code writes', 'org',
        $rule$permit(principal, action == Action::"fs.write", resource)
when { resource has path && (resource.path like "/src/*" || resource.path like "/tests/*") };$rule$,
        TRUE
    );
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

CREATE TRIGGER on_org_created
    AFTER INSERT ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION seed_default_policies();
