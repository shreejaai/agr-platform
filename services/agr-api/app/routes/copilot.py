"""
Copilot — LLM-powered governance assistant.
Gated to paid plans (startup, business, enterprise).
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import CopilotConversation, CopilotMessageRecord
from app.schemas import (
    ConversationDetail,
    ConversationMessageOut,
    ConversationSummary,
    CopilotRequest,
    CopilotResponse,
)
from app.services.copilot_service import CopilotService
from app.services.redis_service import invalidate_conversation_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/copilot", tags=["copilot"])

ALLOWED_PLANS = {"startup", "business", "enterprise"}


@router.post("/chat", response_model=CopilotResponse)
async def copilot_chat(
    body: CopilotRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CopilotResponse:
    org = request.state.org
    org_id = request.state.org_id

    if org.plan not in ALLOWED_PLANS:
        return CopilotResponse(
            message=(
                "The AGR Copilot is available on Startup, Business, and Enterprise plans. "
                "Upgrade at https://agr.dev/pricing to unlock AI-powered policy creation, "
                "agent registration, and more."
            ),
            action_type="error",
            conversation_id="",
            suggestions=["View current plan", "Learn about Copilot features"],
        )

    service = CopilotService(session=session, org_id=org_id, org=org)
    return await service.handle_message(
        message=body.message,
        confirm_preview=body.confirm_preview,
        conversation_id=body.conversation_id,
        auto_confirm=body.auto_confirm,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[ConversationSummary]:
    org_id = request.state.org_id
    result = await session.execute(
        select(CopilotConversation)
        .where(CopilotConversation.org_id == org_id)
        .order_by(CopilotConversation.updated_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    return [
        ConversationSummary(
            id=str(c.id),
            title=c.title,
            message_count=c.message_count,
            updated_at=c.updated_at,
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    org_id = request.state.org_id
    result = await session.execute(
        select(CopilotConversation).where(
            CopilotConversation.id == conversation_id,
            CopilotConversation.org_id == org_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs_result = await session.execute(
        select(CopilotMessageRecord)
        .where(CopilotMessageRecord.conversation_id == conversation_id)
        .order_by(CopilotMessageRecord.created_at.asc())
    )
    msgs = msgs_result.scalars().all()

    return ConversationDetail(
        id=str(conv.id),
        title=conv.title,
        message_count=conv.message_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            ConversationMessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                action_type=m.action_type,
                metadata=m.msg_metadata,
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    org_id = request.state.org_id
    result = await session.execute(
        select(CopilotConversation).where(
            CopilotConversation.id == conversation_id,
            CopilotConversation.org_id == org_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.execute(
        delete(CopilotConversation).where(CopilotConversation.id == conversation_id)
    )
    await session.flush()
    await invalidate_conversation_cache(str(conversation_id))
