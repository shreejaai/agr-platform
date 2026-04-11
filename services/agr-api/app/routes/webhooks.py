"""Webhook CRUD — register URLs to receive approval decision push notifications."""

import ipaddress
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.dependencies import require_role
from app.middleware.auth import require_scope
from app.models import Webhook, WebhookDelivery
from app.schemas import (
    WebhookCreate,
    WebhookDeliveryResponse,
    WebhookResponse,
    WebhookRotateSecretResponse,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.services.webhook_service import build_signature_headers, retry_webhook_delivery

# Private/reserved IP blocks — AGR server cannot reach these from a public host
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local
]

_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _url_reachability_warning(url: str) -> str | None:
    """Return a warning string if the URL is not reachable from a remote AGR server.

    AGR delivers webhooks server-to-server. Localhost/private IPs only work
    if both AGR and the target app are on the same private network.

    Returns None if the URL looks publicly reachable, otherwise a human-readable warning.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().strip("[]")
    except Exception:
        return None

    # Named loopback
    if host in _LOOPBACK_HOSTNAMES:
        return (
            "This URL points to localhost. AGR delivers webhooks server-to-server from a "
            "remote host — it cannot reach your local machine. "
            "Use a public tunnel (ngrok, cloudflared) or a publicly reachable URL instead."
        )

    # Numeric private IP
    try:
        addr = ipaddress.ip_address(host)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return (
                    f"This URL uses a private/reserved IP address ({host}). "
                    "AGR delivers webhooks from a remote server and cannot reach private network addresses. "
                    "Use a publicly reachable URL or a public tunnel (ngrok, cloudflared)."
                )
    except ValueError:
        pass  # not a bare IP — hostname, fine

    return None


router = APIRouter(prefix="/v1", tags=["webhooks"])

_VALID_EVENTS = frozenset(
    [
        "approval.approved",
        "approval.rejected",
        "evaluation.completed",
        "policy.changed",
        "agent.updated",
    ]
)


_SECRET_PLACEHOLDER = "agr_wh_••••••••"


def _to_response(wh: Webhook, reveal_secret: bool = False) -> WebhookResponse:
    """Convert a Webhook model to a response schema.

    Secret is masked on all read endpoints — only revealed once on creation.
    url_warning is populated whenever the stored URL is not publicly reachable.
    """
    return WebhookResponse(
        id=str(wh.id),
        org_id=str(wh.org_id),
        url=wh.url,
        secret=wh.secret if reveal_secret else _SECRET_PLACEHOLDER,
        events=list(wh.events) if wh.events else [],
        active=wh.active,
        rotating_secret_expires_at=wh.rotating_secret_expires_at,
        created_at=wh.created_at,
        url_warning=_url_reachability_warning(wh.url),
    )


@router.post(
    "/webhooks",
    response_model=WebhookResponse,
    status_code=201,
    dependencies=[Depends(require_scope("webhooks:write"))],
)
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


@router.get(
    "/webhooks",
    response_model=list[WebhookResponse],
    dependencies=[Depends(require_scope("webhooks:read"))],
)
async def list_webhooks(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[WebhookResponse]:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.org_id == org_id).order_by(Webhook.created_at.desc())
    )
    return [_to_response(wh) for wh in result.scalars().all()]


@router.get(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    dependencies=[Depends(require_scope("webhooks:read"))],
)
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


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    dependencies=[Depends(require_scope("webhooks:write"))],
)
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


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=204,
    dependencies=[Depends(require_scope("webhooks:write"))],
)
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


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
    dependencies=[Depends(require_scope("webhooks:read"))],
)
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
    dependencies=[Depends(require_scope("webhooks:write")), Depends(require_role("admin"))],
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
    dependencies=[Depends(require_scope("webhooks:write")), Depends(require_role("admin"))],
)
@router.post(
    "/webhooks/{webhook_id}/rotate_secret",
    response_model=WebhookRotateSecretResponse,
    dependencies=[Depends(require_scope("webhooks:write")), Depends(require_role("admin"))],
)
async def rotate_webhook_secret(
    webhook_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookRotateSecretResponse:
    """Generate a new HMAC secret with a temporary grace period for the old one."""
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    grace_expires_at = datetime.now(UTC) + timedelta(hours=settings.webhook_secret_rotation_hours)
    new_secret = "agr_wh_" + secrets.token_hex(24)
    wh.rotating_secret = wh.secret
    wh.rotating_secret_expires_at = grace_expires_at
    wh.secret = new_secret
    await session.flush()
    return WebhookRotateSecretResponse(
        id=str(wh.id),
        new_secret=new_secret,
        rotating_secret_expires_at=grace_expires_at,
        message=(
            f"Old signature accepted for {settings.webhook_secret_rotation_hours} hours. "
            f"Update your endpoint before {grace_expires_at.isoformat()}."
        ),
    )


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=WebhookTestResponse,
    dependencies=[Depends(require_scope("webhooks:write"))],
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
    headers = build_signature_headers(wh, timestamp, body, event)

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
