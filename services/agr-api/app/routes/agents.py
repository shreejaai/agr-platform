"""Agent registration endpoint."""

import uuid

from fastapi import APIRouter, Request

from app.schemas import AgentRegisterRequest

router = APIRouter(prefix="/v1")


@router.post("/agents/register")
async def register_agent(
    body: AgentRegisterRequest,
    request: Request,
) -> dict[str, object]:
    org_id: uuid.UUID = request.state.org_id
    return {
        "agent_id": body.agent_id,
        "org_id": str(org_id),
        "metadata": body.metadata,
        "registered": True,
    }
