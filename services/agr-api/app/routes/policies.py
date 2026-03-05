"""CRUD for Cedar policies."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Policy
from app.schemas import PolicyCreate, PolicyResponse, PolicyUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


def _policy_to_response(p: Policy) -> PolicyResponse:
    return PolicyResponse(
        id=str(p.id),
        org_id=str(p.org_id),
        project_id=str(p.project_id) if p.project_id else None,
        agent_id=p.agent_id,
        name=p.name,
        level=p.level,
        cedar_rule=p.cedar_rule,
        version=p.version,
        active=p.active,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("/policies", response_model=list[PolicyResponse])
async def list_policies(
    request: Request,
    session: AsyncSession = Depends(get_session),
    active: bool | None = None,
) -> list[PolicyResponse]:
    org_id: uuid.UUID = request.state.org_id
    stmt = select(Policy).where(Policy.org_id == org_id)
    if active is not None:
        stmt = stmt.where(Policy.active == active)
    stmt = stmt.order_by(Policy.created_at.desc())
    result = await session.execute(stmt)
    policies = result.scalars().all()
    return [_policy_to_response(p) for p in policies]


@router.post("/policies", response_model=PolicyResponse, status_code=201)
async def create_policy(
    body: PolicyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    policy = Policy(
        id=uuid.uuid4(),
        org_id=org_id,
        project_id=body.project_id,
        agent_id=body.agent_id,
        name=body.name,
        level=body.level,
        cedar_rule=body.cedar_rule,
    )
    session.add(policy)
    await session.flush()
    await session.refresh(policy)
    return _policy_to_response(policy)


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PolicyResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    if body.cedar_rule is not None and body.cedar_rule != policy.cedar_rule:
        policy.cedar_rule = body.cedar_rule
        policy.version += 1
    if body.active is not None:
        policy.active = body.active
    if body.name is not None:
        policy.name = body.name

    await session.flush()
    await session.refresh(policy)
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    await session.delete(policy)
