"""Webhook dispatch service.

Fires HMAC-signed HTTP POST to registered webhook URLs when approval decisions
are made. Fires as a BackgroundTask — never blocks the API response.

Signature format (Stripe-style):
  X-AGR-Signature: t=<unix_timestamp>,v1=<hmac_hex>
  Signed payload:  <timestamp>.<json_body>
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Webhook

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT = 10.0   # seconds per delivery attempt
_MAX_ATTEMPTS = 3         # total tries before giving up
_BACKOFF_BASE = 1.0       # seconds — doubled on each retry (1s, 2s)


def _sign_payload(secret: str, timestamp: int, body: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    signed_content = f"{timestamp}.{body}"
    return hmac.new(secret.encode(), signed_content.encode(), hashlib.sha256).hexdigest()


async def fire_approval_webhook(
    session: AsyncSession,
    org_id: UUID,
    event: str,
    approval_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    decided_by: str,
    reason: str,
) -> None:
    """Load active webhooks for the org and fire the event payload to each URL.

    Called as a BackgroundTask — errors are logged, never re-raised.
    """
    result = await session.execute(
        select(Webhook).where(
            Webhook.org_id == org_id,
            Webhook.active.is_(True),
        )
    )
    webhooks = result.scalars().all()

    matching = [
        wh for wh in webhooks
        if isinstance(wh.events, list) and event in wh.events
    ]

    if not matching:
        return

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

    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
        for wh in matching:
            sig = _sign_payload(str(wh.secret), timestamp, body)
            headers = {
                "Content-Type": "application/json",
                "X-AGR-Signature": f"t={timestamp},v1={sig}",
                "X-AGR-Event": event,
            }
            await _deliver_with_retry(client, wh.id, str(wh.url), body, headers)


async def _deliver_with_retry(
    client: httpx.AsyncClient,
    webhook_id: object,
    url: str,
    body: str,
    headers: dict[str, str],
) -> None:
    """Attempt delivery up to _MAX_ATTEMPTS times with exponential backoff.

    Backoff delays: 1s before attempt 2, 2s before attempt 3.
    Errors are logged and never re-raised — caller is a BackgroundTask.
    """
    delay = _BACKOFF_BASE
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, content=body, headers=headers)
            if resp.is_success:
                logger.info(
                    "Webhook %s delivered to %s (status=%d, attempt=%d)",
                    webhook_id, url, resp.status_code, attempt,
                )
                return
            logger.warning(
                "Webhook %s non-2xx response: %s %d (attempt=%d/%d)",
                webhook_id, url, resp.status_code, attempt, _MAX_ATTEMPTS,
            )
        except Exception as exc:
            logger.warning(
                "Webhook %s delivery error to %s (attempt=%d/%d): %s",
                webhook_id, url, attempt, _MAX_ATTEMPTS, exc,
            )

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(delay)
            delay *= 2

    logger.error(
        "Webhook %s permanently failed after %d attempts to %s",
        webhook_id, _MAX_ATTEMPTS, url,
    )
