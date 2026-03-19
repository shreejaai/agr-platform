"""Organization service — helpers for org lifecycle.

seed_default_policies() mirrors the PostgreSQL trigger in migration 003.
Call this anywhere the trigger doesn't fire (e.g. SQLite in tests, Clerk webhooks).
"""

import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Policy

# Mirrors packages/agr-core/policies/default.cedar
_DEFAULT_POLICIES: list[tuple[str, str]] = [
    (
        "Block production DB drops",
        'forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)\n'
        'when { resource has environment && resource.environment == "production" };',
    ),
    (
        "Require approval for production deploys",
        'forbid(principal, action == Action::"deploy", resource)\n'
        'when { resource has environment && resource.environment == "production" }\n'
        'unless { context has approval_status && context.approval_status == "approved" };',
    ),
    (
        "Block writes to secrets/env files",
        'forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)\n'
        'when { resource has path && (resource.path like "*.env*" || resource.path like "*secrets*") };',
    ),
    (
        "Allow staging auto-deploy",
        'permit(principal, action == Action::"deploy", resource)\n'
        'when { resource has environment && resource.environment == "staging" };',
    ),
    (
        "Allow source code writes",
        'permit(principal, action == Action::"fs.write", resource)\n'
        'when { resource has path && (resource.path like "/src/*" || resource.path like "/tests/*") };',
    ),
]


async def seed_default_policies(session: AsyncSession, org_id: UUID) -> list[Policy]:
    """Insert the 5 default Cedar policies for a newly created org.

    In production this is handled by the PostgreSQL trigger (migration 003).
    Call this explicitly when: creating orgs via Clerk webhook, seeding test orgs,
    or any path that doesn't go through the PostgreSQL trigger.
    """
    policies = [
        Policy(
            id=uuid.uuid4(),
            org_id=org_id,
            name=name,
            level="org",
            cedar_rule=rule,
            active=True,
        )
        for name, rule in _DEFAULT_POLICIES
    ]
    for p in policies:
        session.add(p)
    await session.flush()
    return policies
