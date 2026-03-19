"""Webhook dispatch service.

Fires HMAC-signed HTTP POST to registered webhook URLs when approval decisions
are made. Fires as a BackgroundTask — never blocks the API response.

Signature format (Stripe-style):
  X-AGR-Signature: t=<unix_timestamp>,v1=<hmac_hex>
  Signed payload:  <timestamp>.<json_body>
"""

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
            try:
                resp = await client.post(str(wh.url), content=body, headers=headers)
                if resp.is_success:
                    logger.info("Webhook %s delivered to %s (status=%d)", wh.id, wh.url, resp.status_code)
                else:
                    logger.warning("Webhook %s delivery failed: %s %d", wh.id, wh.url, resp.status_code)
            except Exception as exc:
                logger.warning("Webhook %s delivery error to %s: %s", wh.id, wh.url, exc)
