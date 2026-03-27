"""Integration tests for Slack-based approval decisions."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from app.config import settings
from app.models import ApprovalRequest
from app.services.slack_service import build_slack_approval_message

if TYPE_CHECKING:
    from httpx import AsyncClient


def _slack_headers(secret: str, body: bytes, timestamp: int) -> dict[str, str]:
    base = f"v0:{timestamp}:{body.decode('utf-8')}".encode()
    signature = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": str(timestamp),
        "X-Slack-Signature": signature,
    }


async def _trigger_slack_approval(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "deploy-bot",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production", "secret_name": "customer-pii-db"},
            "approver_email": "approver@example.com",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "APPROVAL_REQUIRED"
    approval_id = response.json()["approval_id"]
    assert isinstance(approval_id, str)
    return approval_id


@pytest.mark.asyncio
async def test_slack_interactivity_approves_pending_request(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_user_email(user_id: str) -> str:
        return "approver@example.com"

    monkeypatch.setattr(settings, "slack_signing_secret", "test-slack-secret")
    monkeypatch.setattr(settings, "slack_team_id", "T123")
    monkeypatch.setattr("app.routes.slack.fetch_slack_user_email", fake_fetch_user_email)

    approval_id = await _trigger_slack_approval(client, auth_headers)
    payload = {
        "team": {"id": "T123"},
        "user": {"id": "U123"},
        "actions": [{"value": json.dumps({"approval_id": approval_id, "decision": "approved"})}],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    headers = _slack_headers("test-slack-secret", body, int(time.time()))

    response = await client.post("/v1/slack/interactivity", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["replace_original"] is True

    approval_response = await client.get(f"/v1/approvals/{approval_id}", headers=auth_headers)
    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_slack_interactivity_rejects_unauthorized_actor(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_user_email(user_id: str) -> str:
        return "intruder@example.com"

    monkeypatch.setattr(settings, "slack_signing_secret", "test-slack-secret")
    monkeypatch.setattr(settings, "slack_team_id", "T123")
    monkeypatch.setattr("app.routes.slack.fetch_slack_user_email", fake_fetch_user_email)

    approval_id = await _trigger_slack_approval(client, auth_headers)
    payload = {
        "team": {"id": "T123"},
        "user": {"id": "U999"},
        "actions": [{"value": json.dumps({"approval_id": approval_id, "decision": "rejected"})}],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    headers = _slack_headers("test-slack-secret", body, int(time.time()))

    response = await client.post("/v1/slack/interactivity", content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["response_type"] == "ephemeral"

    approval_response = await client.get(f"/v1/approvals/{approval_id}", headers=auth_headers)
    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == "pending"


def test_slack_message_redacts_resource_and_context() -> None:
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        agent_id="deploy-bot",
        action="deploy",
        resource="customer-pii-database",
        context={"secret_name": "customer-pii-db", "environment": "production"},
        status="pending",
        approver_email="approver@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    payload = build_slack_approval_message(approval)
    serialized = json.dumps(payload)

    assert "customer-pii-database" not in serialized
    assert "secret_name" not in serialized
