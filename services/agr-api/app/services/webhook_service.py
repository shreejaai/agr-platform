"""Webhook dispatch service.

Fires HMAC-signed HTTP POST to registered webhook URLs when approval decisions
are made. Fires as a BackgroundTask — never blocks the API response.

Every delivery attempt is recorded in webhook_deliveries. Failed deliveries
(after all retries) can be replayed via POST /v1/webhooks/{id}/deliveries/{id}/retry.

Signature format (Stripe-style):
  X-AGR-Signature: t=<unix_timestamp>,v1=<hmac_hex>
  Signed payload:  <timestamp>.<json_body>
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from app.models import Webhook, WebhookDelivery

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT = 10.0  # seconds per delivery attempt
_MAX_ATTEMPTS = 3  # total tries before giving up
_BACKOFF_BASE = 1.0  # seconds — doubled on each retry (1s, 2s)

# M7: 4xx responses (except 429 Too Many Requests) are permanent failures —
# retrying won't help if the endpoint returns 401/403/404.
_PERMANENT_FAILURE_CODES = frozenset(range(400, 500)) - {429}


def _sign_payload(secret: str, timestamp: int, body: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    signed_content = f"{timestamp}.{body}"
    return hmac.new(secret.encode(), signed_content.encode(), hashlib.sha256).hexdigest()


async def fire_approval_webhook(
    org_id: uuid.UUID,
    event: str,
    approval_id: uuid.UUID,
    agent_id: str,
    action: str,
    resource: str,
    decided_by: str,
    reason: str,
) -> None:
    """Load active webhooks for the org and fire the event payload to each URL.

    Opens its own DB session — safe to call as a BackgroundTask after the
    request session has already committed and closed.
    Records every delivery attempt in webhook_deliveries.
    """
    from app.database import async_session_factory

    payload: dict[str, object] = {
        "event": event,
        "approval_id": str(approval_id),
        "org_id": str(org_id),
        "agent_id": agent_id,
        "action": action,
        "resource": resource,
        "decided_by": decided_by,
        "reason": reason,
    }
    body = json.dumps(payload, default=str)
    timestamp = int(time.time())

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Webhook).where(
                    Webhook.org_id == org_id,
                    Webhook.active.is_(True),
                )
            )
            webhooks = result.scalars().all()
            matching = [wh for wh in webhooks if isinstance(wh.events, list) and event in wh.events]

            if not matching:
                return

            async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
                for wh in matching:
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

                    status, http_status, last_error, attempts = await _deliver_with_retry(
                        client, wh.id, str(wh.url), body, headers
                    )

                    delivery.status = status
                    delivery.http_status = http_status
                    delivery.last_error = last_error
                    delivery.attempts = attempts
                    await session.flush()

            await session.commit()
    except Exception as exc:
        logger.error("fire_approval_webhook failed for org %s event %s: %s", org_id, event, exc)


async def retry_webhook_delivery(
    session: AsyncSession,
    webhook_id: uuid.UUID,
    delivery_id: uuid.UUID,
    org_id: uuid.UUID,
) -> WebhookDelivery | None:
    """Re-fire a failed delivery. Creates a new WebhookDelivery record.

    Returns the new delivery, or None if the original delivery is not found
    or does not belong to the org.
    """
    result = await session.execute(
        select(WebhookDelivery, Webhook)
        .join(Webhook, WebhookDelivery.webhook_id == Webhook.id)
        .where(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.webhook_id == webhook_id,
            Webhook.org_id == org_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None

    orig_delivery, wh = row

    body = json.dumps(orig_delivery.payload, default=str)
    timestamp = int(time.time())
    sig = _sign_payload(str(wh.secret), timestamp, body)
    headers = {
        "Content-Type": "application/json",
        "X-AGR-Signature": f"t={timestamp},v1={sig}",
        "X-AGR-Event": orig_delivery.event,
    }

    new_delivery = WebhookDelivery(
        id=uuid.uuid4(),
        webhook_id=wh.id,
        org_id=org_id,
        event=orig_delivery.event,
        payload=orig_delivery.payload,
    )
    session.add(new_delivery)
    await session.flush()

    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
        status, http_status, last_error, attempts = await _deliver_with_retry(
            client, wh.id, str(wh.url), body, headers
        )

    new_delivery.status = status
    new_delivery.http_status = http_status
    new_delivery.last_error = last_error
    new_delivery.attempts = attempts
    return new_delivery


async def _deliver_with_retry(
    client: httpx.AsyncClient,
    webhook_id: object,
    url: str,
    body: str,
    headers: dict[str, str],
) -> tuple[str, int | None, str | None, int]:
    """Attempt delivery up to _MAX_ATTEMPTS times with exponential backoff.

    Returns (status, http_status, last_error, attempts).
    status is "delivered" on success, "failed" after all retries exhausted.
    """
    delay = _BACKOFF_BASE
    last_error: str | None = None
    http_status: int | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, content=body, headers=headers)
            http_status = resp.status_code
            if resp.is_success:
                logger.info(
                    "Webhook %s delivered to %s (status=%d, attempt=%d)",
                    webhook_id,
                    url,
                    resp.status_code,
                    attempt,
                )
                return "delivered", http_status, None, attempt
            last_error = f"HTTP {resp.status_code}"
            logger.warning(
                "Webhook %s non-2xx response: %s %d (attempt=%d/%d)",
                webhook_id,
                url,
                resp.status_code,
                attempt,
                _MAX_ATTEMPTS,
            )
            # M7: don't retry permanent client errors (4xx except 429)
            if resp.status_code in _PERMANENT_FAILURE_CODES:
                logger.error(
                    "Webhook %s permanent failure (HTTP %d) — not retrying",
                    webhook_id,
                    resp.status_code,
                )
                return "failed", http_status, last_error, attempt
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Webhook %s delivery error to %s (attempt=%d/%d): %s",
                webhook_id,
                url,
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(delay)
            delay *= 2

    logger.error(
        "Webhook %s permanently failed after %d attempts to %s",
        webhook_id,
        _MAX_ATTEMPTS,
        url,
    )
    return "failed", http_status, last_error, _MAX_ATTEMPTS
