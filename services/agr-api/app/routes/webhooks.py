"""Webhook CRUD — register URLs to receive approval decision push notifications."""

import json
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models import Webhook, WebhookDelivery
from app.schemas import (
    WebhookCreate,
    WebhookDeliveryResponse,
    WebhookResponse,
    WebhookRotateSecretResponse,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.services.webhook_service import _sign_payload, retry_webhook_delivery

router = APIRouter(prefix="/v1", tags=["webhooks"])

_VALID_EVENTS = frozenset([
    "approval.approved",
    "approval.rejected",
    "evaluation.completed",
    "policy.changed",
    "agent.updated",
])


_SECRET_PLACEHOLDER = "agr_wh_••••••••"


def _to_response(wh: Webhook, reveal_secret: bool = False) -> WebhookResponse:
    """Convert a Webhook model to a response schema.

    Secret is masked on all read endpoints — only revealed once on creation.
    """
    return WebhookResponse(
        id=str(wh.id),
        org_id=str(wh.org_id),
        url=wh.url,
        secret=wh.secret if reveal_secret else _SECRET_PLACEHOLDER,
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
    return _to_response(wh, reveal_secret=True)  # only time the secret is shown


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


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    """Update a webhook's URL, subscribed events, or active status."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    if body.url is not None:
        wh.url = body.url
    if body.events is not None:
        unknown = set(body.events) - _VALID_EVENTS
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown event types: {sorted(unknown)}. Valid: {sorted(_VALID_EVENTS)}",
            )
        wh.events = body.events
    if body.active is not None:
        wh.active = body.active

    await session.flush()
    await session.refresh(wh)
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
    await session.flush()


def _delivery_to_response(d: WebhookDelivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=str(d.id),
        webhook_id=str(d.webhook_id),
        org_id=str(d.org_id),
        event=d.event,
        payload=dict(d.payload) if d.payload else {},
        status=d.status,
        http_status=d.http_status,
        attempts=d.attempts,
        last_error=d.last_error,
        created_at=d.created_at,
    )


@router.get("/webhooks/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_deliveries(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[WebhookDeliveryResponse]:
    """List the last 50 delivery attempts for a webhook (newest first)."""
    org_id: uuid.UUID = request.state.org_id
    # Verify webhook belongs to this org
    wh_result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    if not wh_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Webhook not found.")

    # C3: also filter by org_id to prevent cross-tenant delivery disclosure
    result = await session.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.org_id == org_id,
        )
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
    )
    return [_delivery_to_response(d) for d in result.scalars().all()]


@router.post(
    "/webhooks/{webhook_id}/deliveries/{delivery_id}/retry",
    response_model=WebhookDeliveryResponse,
)
async def retry_delivery(
    webhook_id: uuid.UUID,
    delivery_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookDeliveryResponse:
    """Manually retry a failed webhook delivery. Creates a new delivery record."""
    org_id: uuid.UUID = request.state.org_id
    new_delivery = await retry_webhook_delivery(session, webhook_id, delivery_id, org_id)
    if new_delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return _delivery_to_response(new_delivery)


@router.post(
    "/webhooks/{webhook_id}/rotate-secret",
    response_model=WebhookRotateSecretResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def rotate_webhook_secret(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookRotateSecretResponse:
    """Generate a new HMAC secret for a webhook. Old secret is immediately invalid.

    The new secret is shown once — update your receiver to verify with it.
    """
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    new_secret = "agr_wh_" + secrets.token_hex(24)
    wh.secret = new_secret
    await session.flush()
    return WebhookRotateSecretResponse(id=str(wh.id), new_secret=new_secret)


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=WebhookTestResponse,
)
async def test_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookTestResponse:
    """Send a test ping delivery to a webhook URL to verify connectivity.

    Creates a delivery record with event type 'webhook.test'.
    Uses a synchronous HTTP POST (no retry) — returns the raw HTTP status.
    """
    import httpx

    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    event = "webhook.test"
    payload: dict[str, object] = {
        "event": event,
        "org_id": str(org_id),
        "webhook_id": str(wh.id),
        "message": "This is a test delivery from AGR.",
    }
    body = json.dumps(payload, default=str)
    timestamp = int(time.time())
    sig = _sign_payload(str(wh.secret), timestamp, body)
    headers = {
        "Content-Type": "application/json",
        "X-AGR-Signature": f"t={timestamp},v1={sig}",
        "X-AGR-Event": event,
    }

    delivery = WebhookDelivery(
        id=uuid.uuid4(),
        webhook_id=wh.id,
        org_id=org_id,
        event=event,
        payload=payload,
    )
    session.add(delivery)
    await session.flush()

    http_status: int | None = None
    status = "failed"
    last_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(str(wh.url), content=body, headers=headers)
            http_status = resp.status_code
            status = "success" if resp.status_code < 400 else "failed"
    except Exception as exc:
        last_error = str(exc)[:500]

    delivery.status = status
    delivery.http_status = http_status
    delivery.last_error = last_error
    delivery.attempts = 1
    await session.flush()

    return WebhookTestResponse(
        delivery_id=str(delivery.id),
        status=status,
        http_status=http_status,
    )
