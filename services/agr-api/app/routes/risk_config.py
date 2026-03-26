"""GET/PUT /v1/org/risk-config — per-org risk scoring tuning."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models import OrgRiskConfig
from app.schemas import OrgRiskConfigResponse, OrgRiskConfigUpdate

router = APIRouter(prefix="/v1")

_WEIGHT_FIELDS = [
    "weight_action_severity",
    "weight_context_signals",
    "weight_rate_pattern",
    "weight_agent_trust",
    "weight_amount_scale",
    "weight_resource_sensitivity",
]


def _to_response(cfg: OrgRiskConfig) -> OrgRiskConfigResponse:
    return OrgRiskConfigResponse(
        org_id=str(cfg.org_id),
        weight_action_severity=cfg.weight_action_severity,
        weight_context_signals=cfg.weight_context_signals,
        weight_rate_pattern=cfg.weight_rate_pattern,
        weight_agent_trust=cfg.weight_agent_trust,
        weight_amount_scale=cfg.weight_amount_scale,
        weight_resource_sensitivity=cfg.weight_resource_sensitivity,
        threshold_allow_max=cfg.threshold_allow_max,
        threshold_approval_max=cfg.threshold_approval_max,
        updated_at=cfg.updated_at,
    )


async def _get_or_create(session: AsyncSession, org_id: uuid.UUID) -> OrgRiskConfig:
    result = await session.execute(
        select(OrgRiskConfig).where(OrgRiskConfig.org_id == org_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = OrgRiskConfig(id=uuid.uuid4(), org_id=org_id)
        session.add(cfg)
        await session.flush()
        await session.refresh(cfg)
    return cfg


@router.get("/org/risk-config", response_model=OrgRiskConfigResponse)
async def get_risk_config(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrgRiskConfigResponse:
    """Return current risk scoring config; creates default if not yet customised."""
    org_id: uuid.UUID = request.state.org_id
    cfg = await _get_or_create(session, org_id)
    return _to_response(cfg)


@router.put(
    "/org/risk-config",
    response_model=OrgRiskConfigResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def update_risk_config(
    body: OrgRiskConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrgRiskConfigResponse:
    """Update risk scoring weights/thresholds for this org.

    Weights must sum to ≤ 1.0 after update (advisory — engine normalises anyway).
    threshold_allow_max must be < threshold_approval_max.
    """
    org_id: uuid.UUID = request.state.org_id
    cfg = await _get_or_create(session, org_id)

    for field in _WEIGHT_FIELDS:
        val = getattr(body, field)
        if val is not None:
            setattr(cfg, field, val)

    if body.threshold_allow_max is not None:
        cfg.threshold_allow_max = body.threshold_allow_max
    if body.threshold_approval_max is not None:
        cfg.threshold_approval_max = body.threshold_approval_max

    # Validate threshold ordering
    if cfg.threshold_allow_max >= cfg.threshold_approval_max:
        raise HTTPException(
            status_code=422,
            detail="threshold_allow_max must be less than threshold_approval_max.",
        )

    await session.flush()
    await session.refresh(cfg)
    return _to_response(cfg)
