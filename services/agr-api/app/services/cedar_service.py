"""Cedar policy service — loads policies from DB and evaluates them."""

import contextlib
import logging
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.tracing import get_tracer
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
from policy_engine import (  # type: ignore[import-not-found]  # noqa: E402, I001
    EvaluationResult,
    PolicyShapeResult,
    ValidationResult,
    cedar_cli_available,
    close_cedar_process_pool,
    configure_cedar_process_pool,
    evaluate_policies,
    infer_policy_match as _infer_policy_match,
    initialize_cedar_process_pool,
    set_cedar_degraded,
    validate_cedar_rule as _validate_cedar_rule,
    validate_policy_shape as _validate_policy_shape,
)

logger = logging.getLogger(__name__)


def init_cedar_process_pool(pool_size: int) -> bool:
    configure_cedar_process_pool(pool_size)
    return initialize_cedar_process_pool(pool_size) is not None


def shutdown_cedar_process_pool() -> None:
    close_cedar_process_pool()


def set_cedar_degraded_mode(value: bool) -> None:
    set_cedar_degraded(value)


def is_cedar_cli_available() -> bool:
    return bool(cedar_cli_available())


def validate_cedar_rule(rule: str) -> ValidationResult:
    return _validate_cedar_rule(rule)


def validate_policy_shape(rule: str) -> PolicyShapeResult:
    return _validate_policy_shape(rule)


async def load_active_policies(
    session: AsyncSession, org_id: UUID, agent_id: str | None = None
) -> list[dict[str, str]]:
    """Load active Cedar policies for an organization from the database."""
    tracer = get_tracer()
    span_cm = tracer.start_as_current_span("db.load_policies") if tracer else None
    if span_cm is None:
        stmt = select(Policy).where(
            Policy.org_id == org_id,
            Policy.state == "active",
        )
        if agent_id:
            stmt = stmt.where((Policy.agent_id.is_(None)) | (Policy.agent_id == agent_id))

        result = await session.execute(stmt)
        policies = result.scalars().all()
        return [{"id": str(p.id), "cedar_rule": p.cedar_rule} for p in policies]

    with span_cm as span:
        stmt = select(Policy).where(
            Policy.org_id == org_id,
            Policy.state == "active",
        )
        if agent_id:
            stmt = stmt.where((Policy.agent_id.is_(None)) | (Policy.agent_id == agent_id))

        result = await session.execute(stmt)
        policies = result.scalars().all()
        span.set_attribute("db.policy_count", len(policies))
        return [{"id": str(p.id), "cedar_rule": p.cedar_rule} for p in policies]


def evaluate_policy_set(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    return evaluate_policies(policies, agent_id, action, resource, context)


def infer_policy_match(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    return _infer_policy_match(policies, agent_id, action, resource, context)


async def evaluate_request(
    session: AsyncSession,
    org_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
    no_policy_action: str = "deny",
) -> EvaluationResult:
    """Load policies and evaluate a request against them.

    no_policy_action controls the fallback decision when no active policies exist:
      'deny' | 'allow' | 'approval_required'
    """
    policies = await load_active_policies(session, org_id, agent_id)
    _pool_gauge = None
    try:
        from app.services.metrics_service import cedar_pool_inflight as _pool_gauge

        _pool_gauge.inc()
    except Exception:
        _pool_gauge = None
    try:
        return evaluate_policies(policies, agent_id, action, resource, context, no_policy_action)
    finally:
        if _pool_gauge is not None:
            with contextlib.suppress(Exception):
                _pool_gauge.dec()
