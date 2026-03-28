"""First-run quickstart seed helpers."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import Agent, Organization, Policy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_QUICKSTART_POLICIES: list[tuple[str, str]] = [
    (
        "Starter: Allow all low-risk agent actions",
        "permit(principal, action, resource) when { "
        'context has risk_level && context.risk_level == "low" };',
    ),
    (
        "Starter: Block PII data access",
        'forbid(principal, action == Action::"read_pii", resource);',
    ),
    (
        "Starter: Require approval for production deployments",
        'forbid(principal, action == Action::"deploy", resource) '
        'when { context has environment && context.environment == "production" } '
        'unless { context has approval_status && context.approval_status == "approved" };',
    ),
]


async def run_quickstart_seed(session: AsyncSession, org: Organization) -> bool:
    active_policy_count = await session.scalar(
        select(Policy).where(Policy.org_id == org.id, Policy.state == "active").limit(1)
    )
    if org.eval_count != 0 or active_policy_count is not None:
        return False

    for name, cedar_rule in _QUICKSTART_POLICIES:
        session.add(
            Policy(
                id=uuid.uuid4(),
                org_id=org.id,
                name=name,
                level="org",
                cedar_rule=cedar_rule,
                state="active",
                active=True,
            )
        )

    session.add(
        Agent(
            id=uuid.uuid4(),
            org_id=org.id,
            agent_id="example-agent",
            agent_metadata={"description": "Example agent created during quickstart."},
            name="example-agent",
            owner="quickstart",
            framework="example",
            environment="development",
            trust_level="verified",
            capabilities=["evaluate", "deploy"],
            active=True,
        )
    )
    await session.flush()
    logger.info("Quickstart seed applied. Visit /docs to explore the API.")
    return True
