"""Agent registration and listing endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Agent
from app.schemas import AgentRegisterRequest, AgentResponse, AgentUpdateRequest

router = APIRouter(prefix="/v1")


def _to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        org_id=str(agent.org_id),
        agent_id=agent.agent_id,
        metadata=agent.agent_metadata,
        active=agent.active,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("/agents/register", response_model=AgentResponse, status_code=200)
async def register_agent(
    body: AgentRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Register or update an agent for this org.

    Upserts on (org_id, agent_id) — registering the same agent_id again
    updates its metadata and returns the existing record.
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
        )
        session.add(agent)
    else:
        agent.agent_metadata = body.metadata or {}

    await session.flush()
    await session.refresh(agent)
    return _to_response(agent)


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Update an agent's metadata or active status."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    meta = dict(agent.agent_metadata or {})
    if body.name is not None:
        meta["name"] = body.name
    if body.description is not None:
        meta["description"] = body.description
    if body.framework is not None:
        meta["framework"] = body.framework
    agent.agent_metadata = meta

    if body.active is not None:
        agent.active = body.active

    await session.flush()
    await session.refresh(agent)
    return _to_response(agent)


@router.delete("/agents/{agent_id}", status_code=204)
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


@router.get("/agents/{agent_id}", response_model=AgentResponse)
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


@router.get("/agents", response_model=list[AgentResponse])
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
