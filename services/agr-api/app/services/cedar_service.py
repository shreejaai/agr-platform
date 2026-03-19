"""Cedar policy service — loads policies from DB and evaluates them."""

import logging
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Policy

# Resolve agr-core: walk up from this file looking for packages/agr-core,
# then fall back to /packages/agr-core (Docker image path).
_agr_core: str | None = None
for _p in Path(__file__).resolve().parents:
    _candidate = _p / "packages" / "agr-core"
    if _candidate.exists():
        _agr_core = str(_candidate)
        break
sys.path.insert(0, _agr_core or "/packages/agr-core")
from policy_engine import EvaluationResult, evaluate_policies  # noqa: E402

logger = logging.getLogger(__name__)


async def load_active_policies(
    session: AsyncSession, org_id: UUID, agent_id: str | None = None
) -> list[dict[str, str]]:
    """Load active Cedar policies for an organization from the database."""
    stmt = select(Policy).where(
        Policy.org_id == org_id,
        Policy.active.is_(True),
    )
    if agent_id:
        stmt = stmt.where((Policy.agent_id.is_(None)) | (Policy.agent_id == agent_id))

    result = await session.execute(stmt)
    policies = result.scalars().all()

    return [{"id": str(p.id), "cedar_rule": p.cedar_rule} for p in policies]


async def evaluate_request(
    session: AsyncSession,
    org_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Load policies and evaluate a request against them."""
    policies = await load_active_policies(session, org_id, agent_id)
    return evaluate_policies(policies, agent_id, action, resource, context)
