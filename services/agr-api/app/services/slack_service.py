"""Slack notification service.

Posts an approval-required Block Kit message with real one-click approve/reject
buttons to a configured Slack channel. Retries up to 3 times with exponential
backoff. No-ops if SLACK_BOT_TOKEN or SLACK_CHANNEL_ID is not set.
Errors are logged and never re-raised.
"""

import asyncio
import logging

import httpx

from app.config import settings
from app.models import ApprovalRequest
from app.services.notification_service import make_decision_token

logger = logging.getLogger(__name__)

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT = 10.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


async def send_approval_slack(approval: ApprovalRequest) -> None:
    """Post an approval-required notification to Slack.

    No-ops if SLACK_BOT_TOKEN or SLACK_CHANNEL_ID is blank.
    Retries up to 3 times with exponential backoff on transient errors.
    Errors are logged and never re-raised.
    """
    if not settings.slack_bot_token or not settings.slack_channel_id:
        logger.debug(
            "Skipping Slack notification: token configured=%s, channel configured=%s",
            bool(settings.slack_bot_token),
            bool(settings.slack_channel_id),
        )
        return

    # Generate real HMAC-signed tokens for one-click approve/reject URL buttons
    approve_token = make_decision_token(str(approval.id), "approved")
    reject_token = make_decision_token(str(approval.id), "rejected")
    approve_url = f"{settings.api_base_url}/v1/approvals/decide?token={approve_token}"
    reject_url = f"{settings.api_base_url}/v1/approvals/decide?token={reject_token}"

    text = (
        f":rotating_light: *Approval required* — Agent `{approval.agent_id}` "
        f"wants to *{approval.action}* on `{approval.resource}`."
    )

    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:*\n`{approval.agent_id}`"},
                {"type": "mrkdwn", "text": f"*Action:*\n`{approval.action}`"},
                {"type": "mrkdwn", "text": f"*Resource:*\n`{approval.resource}`"},
                {"type": "mrkdwn", "text": f"*Approval ID:*\n`{approval.id}`"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "url": approve_url,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "url": reject_url,
                    "style": "danger",
                },
            ],
        },
    ]

    payload: dict[str, object] = {
        "channel": settings.slack_channel_id,
        "text": text,  # fallback for push notifications
        "blocks": blocks,
    }
    headers = {
        "Authorization": f"Bearer {settings.slack_bot_token}",
        "Content-Type": "application/json",
    }

    delay = _BACKOFF_BASE
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await client.post(_SLACK_API_URL, json=payload, headers=headers)
                data = resp.json()
                if data.get("ok"):
                    logger.info(
                        "Slack notification sent for approval %s (attempt %d)",
                        approval.id,
                        attempt,
                    )
                    return
                logger.warning(
                    "Slack API error for approval %s (attempt %d/%d): %s",
                    approval.id,
                    attempt,
                    _MAX_RETRIES,
                    data.get("error", "unknown"),
                )
            except Exception:
                logger.exception(
                    "Slack delivery exception for approval %s (attempt %d/%d)",
                    approval.id,
                    attempt,
                    _MAX_RETRIES,
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= 2

    logger.error(
        "Slack notification permanently failed for approval %s after %d attempts",
        approval.id,
        _MAX_RETRIES,
    )
