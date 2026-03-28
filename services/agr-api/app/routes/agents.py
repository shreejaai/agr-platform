"""Agent registration and listing endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_scope
from app.models import Agent
from app.schemas import (
    AgentBehaviorResponse,
    AgentRegisterRequest,
    AgentResponse,
    AgentUpdateRequest,
)
from app.services.anomaly_service import get_action_baseline, get_recent_anomalies

router = APIRouter(prefix="/v1", tags=["agents"])


def _to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        org_id=str(agent.org_id),
        agent_id=agent.agent_id,
        metadata=agent.agent_metadata,
        name=agent.name,
        owner=agent.owner,
        framework=agent.framework,
        environment=agent.environment,
        trust_level=agent.trust_level,
        capabilities=agent.capabilities or [],
        active=agent.active,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post(
    "/agents/register",
    response_model=AgentResponse,
    status_code=200,
    dependencies=[Depends(require_scope("agents:write"))],
)
async def register_agent(
    body: AgentRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Register or update an agent for this org.

    Upserts on (org_id, agent_id) — registering the same agent_id again
    updates its profile fields and metadata.
    """
    org_id: uuid.UUID = request.state.org_id

    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.agent_id == body.agent_id)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        agent = Agent(
            id=uuid.uuid4(),
            org_id=org_id,
            agent_id=body.agent_id,
            agent_metadata=body.metadata or {},
            name=body.name,
            owner=body.owner,
            framework=body.framework,
            environment=body.environment,
            trust_level=body.trust_level,
            capabilities=body.capabilities,
        )
        session.add(agent)
    else:
        agent.agent_metadata = body.metadata or {}
        if body.name is not None:
            agent.name = body.name
        if body.owner is not None:
            agent.owner = body.owner
        if body.framework is not None:
            agent.framework = body.framework
        if body.environment is not None:
            agent.environment = body.environment
        agent.trust_level = body.trust_level
        if body.capabilities:
            agent.capabilities = body.capabilities

    await session.flush()
    await session.refresh(agent)
    return _to_response(agent)


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_scope("agents:write"))],
)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Update an agent's profile fields or active status."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    if body.name is not None:
        agent.name = body.name
    if body.owner is not None:
        agent.owner = body.owner
    if body.framework is not None:
        agent.framework = body.framework
    if body.environment is not None:
        agent.environment = body.environment
    if body.trust_level is not None:
        agent.trust_level = body.trust_level
    if body.capabilities is not None:
        agent.capabilities = body.capabilities
    if body.active is not None:
        agent.active = body.active

    # Keep legacy metadata in sync for description
    meta = dict(agent.agent_metadata or {})
    if body.description is not None:
        meta["description"] = body.description
        agent.agent_metadata = meta

    await session.flush()
    await session.refresh(agent)
    return _to_response(agent)


@router.delete(
    "/agents/{agent_id}",
    status_code=204,
    dependencies=[Depends(require_scope("agents:write"))],
)
async def delete_agent(
    agent_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a registered agent."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    await session.delete(agent)
    await session.flush()


@router.get(
    "/agents/{agent_id}/behavior",
    response_model=AgentBehaviorResponse,
    dependencies=[Depends(require_scope("agents:read"))],
)
async def get_agent_behavior(
    agent_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentBehaviorResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.agent_id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")

    org_id_str = str(org_id)
    return AgentBehaviorResponse(
        agent_id=agent.agent_id,
        action_baseline=await get_action_baseline(org_id_str, agent.agent_id),
        anomalies_detected=await get_recent_anomalies(org_id_str, agent.agent_id),
    )


@router.get(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_scope("agents:read"))],
)
async def get_agent(
    agent_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return _to_response(agent)


@router.get(
    "/agents",
    response_model=list[AgentResponse],
    dependencies=[Depends(require_scope("agents:read"))],
)
async def list_agents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[AgentResponse]:
    """List all registered agents for this org."""
    org_id: uuid.UUID = request.state.org_id

    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at.desc())
    )
    agents = result.scalars().all()
    return [_to_response(a) for a in agents]
