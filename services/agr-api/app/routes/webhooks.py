"""Webhook CRUD — register URLs to receive approval decision push notifications."""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Webhook
from app.schemas import WebhookCreate, WebhookResponse

router = APIRouter(prefix="/v1")

_VALID_EVENTS = frozenset(["approval.approved", "approval.rejected"])


def _to_response(wh: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=str(wh.id),
        org_id=str(wh.org_id),
        url=wh.url,
        secret=wh.secret,
        events=list(wh.events) if wh.events else [],
        active=wh.active,
        created_at=wh.created_at,
    )


@router.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    """Register a webhook URL. The secret is shown once — store it securely."""
    org_id: uuid.UUID = request.state.org_id

    unknown = set(body.events) - _VALID_EVENTS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event types: {sorted(unknown)}. Valid: {sorted(_VALID_EVENTS)}",
        )

    wh = Webhook(
        id=uuid.uuid4(),
        org_id=org_id,
        url=body.url,
        secret="agr_wh_" + secrets.token_hex(24),
        events=body.events,
        active=True,
    )
    session.add(wh)
    await session.flush()
    await session.refresh(wh)
    return _to_response(wh)


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[WebhookResponse]:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.org_id == org_id).order_by(Webhook.created_at.desc())
    )
    return [_to_response(wh) for wh in result.scalars().all()]


@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return _to_response(wh)


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    await session.delete(wh)
