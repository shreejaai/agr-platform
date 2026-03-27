"""Slack approval notification and verification helpers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING, Literal

import httpx

from app.config import settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.models import ApprovalRequest

logger = logging.getLogger(__name__)

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_SLACK_USERS_INFO_URL = "https://slack.com/api/users.info"
_TIMEOUT = 10.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_SLACK_SIGNATURE_WINDOW_SECONDS = 60 * 5


def build_slack_approval_message(approval: ApprovalRequest) -> dict[str, object]:
    """Build a minimal Slack payload without exposing resource or context details."""
    action_value_approve = json.dumps(
        {"approval_id": str(approval.id), "decision": "approved"},
        separators=(",", ":"),
    )
    action_value_reject = json.dumps(
        {"approval_id": str(approval.id), "decision": "rejected"},
        separators=(",", ":"),
    )
    dashboard_url = f"{settings.dashboard_base_url.rstrip('/')}/approvals?approvalId={approval.id}"

    text = (
        f"Approval required for action '{approval.action}' "
        f"requested by agent '{approval.agent_id}'."
    )

    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*AGR approval required*\n"
                    f"Action `{approval.action}` requested by agent `{approval.agent_id}`."
                ),
            },
            "fields": [
                {"type": "mrkdwn", "text": f"*Action:*\n`{approval.action}`"},
                {"type": "mrkdwn", "text": f"*Agent:*\n`{approval.agent_id}`"},
                {"type": "mrkdwn", "text": f"*Approval ID:*\n`{approval.id}`"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "approval.approve",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": action_value_approve,
                },
                {
                    "type": "button",
                    "action_id": "approval.reject",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": action_value_reject,
                },
                {
                    "type": "button",
                    "action_id": "approval.open",
                    "text": {"type": "plain_text", "text": "Open in AGR"},
                    "url": dashboard_url,
                },
            ],
        },
    ]

    return {
        "channel": settings.slack_channel_id,
        "text": text,
        "blocks": blocks,
    }


def build_slack_resolution_message(
    approval: ApprovalRequest,
    decision: str,
    actor_email: str,
    *,
    already_resolved: bool = False,
) -> dict[str, object]:
    status_text = "already resolved" if already_resolved else decision
    title = "AGR approval updated" if not already_resolved else "AGR approval already resolved"
    dashboard_url = f"{settings.dashboard_base_url.rstrip('/')}/approvals?approvalId={approval.id}"

    return {
        "replace_original": True,
        "text": f"{title}: {approval.id} is {status_text}.",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{title}*\n"
                        f"Approval `{approval.id}` is now *{status_text}*.\n"
                        f"Recorded by `{actor_email}`."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approval.open",
                        "text": {"type": "plain_text", "text": "Open in AGR"},
                        "url": dashboard_url,
                    }
                ],
            },
        ],
    }


def parse_slack_action_value(value: str) -> tuple[str, Literal["approved", "rejected"]] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    approval_id = payload.get("approval_id")
    decision = payload.get("decision")
    if not isinstance(approval_id, str) or not isinstance(decision, str):
        return None
    if decision == "approved":
        return approval_id, "approved"
    if decision == "rejected":
        return approval_id, "rejected"
    return None


def verify_slack_signature(headers: Mapping[str, str], raw_body: bytes) -> bool:
    """Verify Slack interactivity request signature."""
    if not settings.slack_signing_secret:
        logger.warning("Slack signing secret is not configured.")
        return False

    timestamp = headers.get("X-Slack-Request-Timestamp")
    signature = headers.get("X-Slack-Signature")
    if not timestamp or not signature:
        return False

    try:
        request_time = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - request_time) > _SLACK_SIGNATURE_WINDOW_SECONDS:
        logger.warning("Rejected Slack request outside signature window.")
        return False

    base = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode()
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode("utf-8"),
            base,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


async def fetch_slack_user_email(user_id: str) -> str | None:
    """Resolve the Slack actor's email for approval authorization."""
    if not settings.slack_bot_token or not user_id:
        return None

    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _SLACK_USERS_INFO_URL,
                headers=headers,
                params={"user": user_id},
            )
            data = response.json()
    except Exception:
        logger.exception("Failed to fetch Slack user profile for %s", user_id)
        return None

    if not data.get("ok"):
        logger.warning("Slack users.info failed for %s: %s", user_id, data.get("error"))
        return None

    user = data.get("user")
    if not isinstance(user, dict):
        return None
    profile = user.get("profile")
    if not isinstance(profile, dict):
        return None
    email = profile.get("email")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


async def send_approval_slack(approval: ApprovalRequest) -> None:
    """Post an approval notification to Slack with interactive approve/reject buttons."""
    if (
        not settings.slack_bot_token
        or not settings.slack_channel_id
        or not settings.slack_signing_secret
    ):
        logger.debug(
            "Skipping Slack notification: token=%s channel=%s signing_secret=%s",
            bool(settings.slack_bot_token),
            bool(settings.slack_channel_id),
            bool(settings.slack_signing_secret),
        )
        return

    payload = build_slack_approval_message(approval)
    headers = {
        "Authorization": f"Bearer {settings.slack_bot_token}",
        "Content-Type": "application/json",
    }

    delay = _BACKOFF_BASE
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await client.post(_SLACK_POST_MESSAGE_URL, json=payload, headers=headers)
                data = response.json()
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
