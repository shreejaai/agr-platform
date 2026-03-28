"""Replay historical evaluations against a selected policy set."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditEvent, Policy
from app.schemas import ReplayResponse
from app.services.cedar_service import evaluate_policy_set, load_active_policies

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _load_eval_event(session: AsyncSession, org_id: UUID, eval_id: str) -> AuditEvent:
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.recorded_at.desc())
    )
    for event in result.scalars():
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("eval_id") == eval_id:
            return event
    raise HTTPException(status_code=404, detail="Evaluation not found.")


async def _load_replay_policies(
    session: AsyncSession,
    org_id: UUID,
    agent_id: str,
    policy_ids: list[str] | None,
) -> list[dict[str, str]]:
    if policy_ids is None:
        return await load_active_policies(session, org_id, agent_id)

    normalized_ids = [UUID(policy_id) for policy_id in policy_ids]
    result = await session.execute(
        select(Policy).where(
            Policy.org_id == org_id,
            Policy.id.in_(normalized_ids),
        )
    )
    return [{"id": str(policy.id), "cedar_rule": policy.cedar_rule} for policy in result.scalars()]


async def replay_evaluation(
    session: AsyncSession,
    org_id: UUID,
    eval_id: str,
    policy_ids: list[str] | None = None,
) -> ReplayResponse:
    event = await _load_eval_event(session, org_id, eval_id)
    payload = event.payload if isinstance(event.payload, dict) else {}
    context = payload.get("context")
    normalized_context = context if isinstance(context, dict) else {}

    policies = await _load_replay_policies(session, org_id, event.agent_id, policy_ids)
    replay_result = evaluate_policy_set(
        policies,
        event.agent_id,
        event.action,
        event.resource,
        normalized_context,
    )

    original_risk_score = payload.get("risk_score")
    if isinstance(original_risk_score, bool) or not isinstance(
        original_risk_score, int | type(None)
    ):
        original_risk_score = None
    original_policy_source = payload.get("policy_source")

    return ReplayResponse(
        eval_id=eval_id,
        original_decision=event.decision,
        replayed_decision=replay_result.decision,
        changed=event.decision != replay_result.decision,
        original_policy_source=(
            str(original_policy_source) if original_policy_source is not None else None
        ),
        replayed_policy_source=replay_result.policy_source,
        original_risk_score=original_risk_score,
        replayed_risk_score=original_risk_score,
        replayed_at=datetime.now(UTC),
    )
