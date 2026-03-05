// Block production DB drops
forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)
when { resource has environment && resource.environment == "production" };

// Require approval for production deployments
forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" }
unless { context has approval_status && context.approval_status == "approved" };

// Block writes to secrets/env files
forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)
when { resource has path && (resource.path like "*.env*" || resource.path like "*secrets*") };

// Allow staging auto-deploy
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };

// Allow source code writes
permit(principal, action == Action::"fs.write", resource)
when { resource has path && (resource.path like "/src/*" || resource.path like "/tests/*") };
