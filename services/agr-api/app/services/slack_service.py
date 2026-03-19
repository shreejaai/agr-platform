"""Slack notification service.

Posts an approval-required message to a configured Slack channel when
an agent action needs human review.

No-ops gracefully if SLACK_BOT_TOKEN or SLACK_CHANNEL_ID is not set.
Uses the Slack Web API chat.postMessage endpoint directly via httpx
(no Slack SDK dependency needed).
"""

import logging

import httpx

from app.config import settings
from app.models import ApprovalRequest

logger = logging.getLogger(__name__)

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT = 10.0


async def send_approval_slack(approval: ApprovalRequest) -> None:
    """Post an approval-required notification to Slack.

    No-ops if SLACK_BOT_TOKEN or SLACK_CHANNEL_ID is blank.
    Errors are logged and never re-raised.
    """
    if not settings.slack_bot_token or not settings.slack_channel_id:
        logger.debug(
            "Skipping Slack notification: token configured=%s, channel configured=%s",
            bool(settings.slack_bot_token),
            bool(settings.slack_channel_id),
        )
        return

    approve_url = (
        f"{settings.api_base_url}/v1/approvals/decide"
        f"?token=_placeholder_"  # real token generated at call site if needed
    )

    text = (
        f":rotating_light: *Approval required* — Agent `{approval.agent_id}` "
        f"wants to *{approval.action}* on `{approval.resource}`."
    )

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:*\n{approval.agent_id}"},
                {"type": "mrkdwn", "text": f"*Action:*\n{approval.action}"},
                {"type": "mrkdwn", "text": f"*Resource:*\n{approval.resource}"},
                {"type": "mrkdwn", "text": f"*Approval ID:*\n`{approval.id}`"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Review in Dashboard"},
                    "url": f"{settings.api_base_url}/approvals/{approval.id}",
                    "style": "primary",
                }
            ],
        },
    ]

    payload = {
        "channel": settings.slack_channel_id,
        "text": text,          # fallback for notifications
        "blocks": blocks,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _SLACK_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.slack_bot_token}",
                    "Content-Type": "application/json",
                },
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning(
                    "Slack API returned error for approval %s: %s",
                    approval.id,
                    data.get("error", "unknown"),
                )
            else:
                logger.info("Slack notification sent for approval %s", approval.id)
    except Exception:
        logger.exception("Failed to send Slack notification for approval %s", approval.id)
