"""Slack interactive approval route."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.config import settings
from app.database import get_session
from app.models import ApprovalRequest, OrgMember
from app.routes.approvals import _apply_decision, _load_pending
from app.services.slack_service import (
    build_slack_resolution_message,
    fetch_slack_user_email,
    parse_slack_action_value,
    verify_slack_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["approvals"])

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _ephemeral_response(message: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "response_type": "ephemeral",
            "replace_original": False,
            "text": message,
        },
    )


async def _is_authorized_slack_actor(
    session: AsyncSession,
    approval: ApprovalRequest,
    actor_email: str,
) -> bool:
    normalized = actor_email.strip().lower()
    if approval.approver_email:
        return normalized == approval.approver_email.strip().lower()

    result = await session.execute(
        select(OrgMember).where(
            OrgMember.org_id == approval.org_id,
            func.lower(OrgMember.email) == normalized,
            OrgMember.status == "active",
        )
    )
    member = result.scalar_one_or_none()
    return member is not None and member.role in {"admin", "operator"}


@router.post("/slack/interactivity")
async def handle_slack_interactivity(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    raw_body = await request.body()
    if not verify_slack_signature(request.headers, raw_body):
        return _ephemeral_response("Invalid Slack signature.", status_code=401)

    form = parse_qs(raw_body.decode("utf-8"))
    payload_raw = form.get("payload", [None])[0]
    if not payload_raw:
        return _ephemeral_response("Missing Slack payload.", status_code=400)

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return _ephemeral_response("Invalid Slack payload.", status_code=400)

    if not isinstance(payload, dict):
        return _ephemeral_response("Invalid Slack payload.", status_code=400)

    if settings.slack_team_id:
        team = payload.get("team")
        team_id = team.get("id") if isinstance(team, dict) else None
        if team_id != settings.slack_team_id:
            return _ephemeral_response("Slack workspace is not authorized.", status_code=403)

    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return _ephemeral_response("Missing Slack action.", status_code=400)

    action = actions[0]
    if not isinstance(action, dict):
        return _ephemeral_response("Invalid Slack action.", status_code=400)

    value = action.get("value")
    parsed_value = parse_slack_action_value(str(value))
    if parsed_value is None:
        return _ephemeral_response("Invalid approval action payload.", status_code=400)
    approval_id_raw, decision = parsed_value

    user = payload.get("user")
    slack_user_id = user.get("id") if isinstance(user, dict) else None
    actor_email = await fetch_slack_user_email(str(slack_user_id or ""))
    if actor_email is None:
        return _ephemeral_response(
            "Could not verify your Slack identity. Ensure users:read.email is granted.",
            status_code=403,
        )

    try:
        approval_uuid = uuid.UUID(approval_id_raw)
    except ValueError:
        return _ephemeral_response("Invalid approval identifier.", status_code=400)

    result = await session.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_uuid).with_for_update()
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        return _ephemeral_response("Approval request not found.", status_code=404)

    if not await _is_authorized_slack_actor(session, approval, actor_email):
        logger.warning(
            "Unauthorized Slack approval attempt for %s by %s",
            approval.id,
            actor_email,
        )
        return _ephemeral_response(
            "You are not authorized to approve this request in Slack.",
            status_code=403,
        )

    if approval.status != "pending":
        return JSONResponse(
            content=build_slack_resolution_message(
                approval,
                approval.status,
                actor_email,
                already_resolved=True,
            )
        )

    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if datetime.now(UTC) > expires:
        return _ephemeral_response("This approval request has expired.", status_code=410)

    try:
        approval = await _load_pending(approval_uuid, approval.org_id, session)
    except HTTPException as exc:
        return _ephemeral_response(str(exc.detail), status_code=exc.status_code)

    await _apply_decision(
        approval,
        decision=decision,
        decided_by=f"slack:{actor_email}",
        reason="Decision recorded from Slack interactive approval.",
        session=session,
        background_tasks=background_tasks,
    )
    return JSONResponse(content=build_slack_resolution_message(approval, decision, actor_email))
