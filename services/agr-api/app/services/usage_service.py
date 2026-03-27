"""Usage tracking and soft quota helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from app.models import EvaluationUsage

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Organization


@dataclass(slots=True)
class QuotaStatus:
    total_evaluations: int
    usage_pct: int
    quota_state: Literal["ok", "warning", "exceeded"]
    warning_message: str | None


def determine_quota_status(
    total_evaluations: int,
    eval_limit: int,
    warning_threshold_pct: int,
    soft_limit_enabled: bool,
) -> QuotaStatus:
    if eval_limit <= 0:
        return QuotaStatus(
            total_evaluations=total_evaluations,
            usage_pct=0,
            quota_state="ok",
            warning_message=None,
        )

    usage_pct = max(0, round((total_evaluations / eval_limit) * 100))

    if total_evaluations > eval_limit:
        warning = (
            f"Usage is above the configured evaluation quota ({total_evaluations}/{eval_limit}). "
            "Soft enforcement is active, so evaluations continue while administrators review usage."
            if soft_limit_enabled
            else (
                "Usage is above the configured evaluation quota "
                f"({total_evaluations}/{eval_limit})."
            )
        )
        return QuotaStatus(total_evaluations, usage_pct, "exceeded", warning)

    if usage_pct >= warning_threshold_pct:
        return QuotaStatus(
            total_evaluations=total_evaluations,
            usage_pct=usage_pct,
            quota_state="warning",
            warning_message=(
                f"Usage has reached {usage_pct}% of the configured quota "
                f"({total_evaluations}/{eval_limit})."
            ),
        )

    return QuotaStatus(
        total_evaluations=total_evaluations,
        usage_pct=usage_pct,
        quota_state="ok",
        warning_message=None,
    )


async def record_evaluation_usage(
    session: AsyncSession,
    org_id: UUID,
    agent_id: str,
    occurred_at: datetime | None = None,
) -> None:
    timestamp = occurred_at or datetime.now(UTC)
    result = await session.execute(
        select(EvaluationUsage).where(
            EvaluationUsage.org_id == org_id,
            EvaluationUsage.agent_id == agent_id,
        )
    )
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = EvaluationUsage(
            org_id=org_id,
            agent_id=agent_id,
            total_evaluations=1,
            last_evaluated_at=timestamp,
        )
        session.add(usage)
        return

    usage.total_evaluations += 1
    usage.last_evaluated_at = timestamp


def should_emit_soft_limit_warning(org: Organization, status: QuotaStatus) -> bool:
    if status.quota_state not in {"warning", "exceeded"}:
        return False
    last_warned = org.usage_last_warned_count or 0
    return status.total_evaluations > last_warned
