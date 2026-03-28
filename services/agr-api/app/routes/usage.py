"""Usage and soft quota visibility endpoints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from app.database import get_session
from app.middleware.auth import require_scope
from app.models import EvaluationUsage, Organization
from app.schemas import AgentUsageResponse, UsageResponse
from app.services.redis_service import get_current_eval_count
from app.services.usage_service import determine_quota_status

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/v1", tags=["org"])


@router.get(
    "/usage",
    response_model=UsageResponse,
    dependencies=[Depends(require_scope("org:admin"))],
)
async def get_usage(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> UsageResponse:
    org: Organization = request.state.org
    org_id: uuid.UUID = request.state.org_id
    live_total = await get_current_eval_count(org_id, org.eval_count)
    persisted_total = await session.scalar(
        select(func.coalesce(func.sum(EvaluationUsage.total_evaluations), 0)).where(
            EvaluationUsage.org_id == org_id
        )
    )
    effective_total = max(live_total, int(persisted_total or 0))
    quota = determine_quota_status(
        total_evaluations=effective_total,
        eval_limit=org.eval_limit,
        warning_threshold_pct=org.eval_warning_threshold_pct,
        soft_limit_enabled=org.eval_soft_limit_enabled,
    )

    result = await session.execute(
        select(EvaluationUsage)
        .where(EvaluationUsage.org_id == org_id)
        .order_by(EvaluationUsage.total_evaluations.desc(), EvaluationUsage.agent_id.asc())
        .limit(20)
    )
    usage_rows = result.scalars().all()

    per_agent: list[AgentUsageResponse] = []
    for row in usage_rows:
        share_pct = (
            round((row.total_evaluations / effective_total) * 100) if effective_total > 0 else 0
        )
        per_agent.append(
            AgentUsageResponse(
                agent_id=row.agent_id,
                total_evaluations=row.total_evaluations,
                share_pct=share_pct,
                last_evaluated_at=row.last_evaluated_at,
            )
        )

    return UsageResponse(
        org_id=str(org_id),
        total_evaluations=effective_total,
        eval_limit=org.eval_limit,
        eval_warning_threshold_pct=org.eval_warning_threshold_pct,
        eval_soft_limit_enabled=org.eval_soft_limit_enabled,
        usage_pct=quota.usage_pct,
        quota_state=quota.quota_state,
        warning_message=quota.warning_message,
        per_agent=per_agent,
    )
