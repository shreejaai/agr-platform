"""Integration tests for approval flow."""

import pytest
from httpx import AsyncClient

from app.services.notification_service import make_decision_token, verify_decision_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _trigger_approval(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    """Trigger an APPROVAL_REQUIRED evaluate and return the approval_id."""
    resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "APPROVAL_REQUIRED"
    return resp.json()["approval_id"]


# ---------------------------------------------------------------------------
# Existing flow (kept, now via shared helper)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_flow_evaluate_approve(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Full flow: evaluate → APPROVAL_REQUIRED → approve → status=approved."""
    approval_id = await _trigger_approval(client, auth_headers)

    list_resp = await client.get(
        "/v1/approvals", params={"status": "pending"}, headers=auth_headers
    )
    assert list_resp.status_code == 200
    assert any(a["id"] == approval_id for a in list_resp.json())

    approve_resp = await client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={"decided_by": "test-user", "reason": "Looks good"},
        headers=auth_headers,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"
    assert approve_resp.json()["decision_at"] is not None


@pytest.mark.asyncio
async def test_approval_reject(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    reject_resp = await client.post(
        f"/v1/approvals/{approval_id}/reject",
        json={"decided_by": "test-user", "reason": "Not ready"},
        headers=auth_headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"
    assert reject_resp.json()["decision_at"] is not None


@pytest.mark.asyncio
async def test_approval_double_approve_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    await client.post(f"/v1/approvals/{approval_id}/approve", json={}, headers=auth_headers)
    second = await client.post(
        f"/v1/approvals/{approval_id}/approve", json={}, headers=auth_headers
    )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/approvals/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_approval_by_id(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    resp = await client.get(f"/v1/approvals/{approval_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == approval_id
    assert data["status"] == "pending"
    assert data["action"] == "deploy"
    assert data["resource"] == "production-server"


@pytest.mark.asyncio
async def test_get_approval_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    import uuid
    resp = await client.get(
        f"/v1/approvals/{uuid.uuid4()}", headers=auth_headers
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/approvals/{id}/decide
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decide_approve(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    resp = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approved", "decided_by": "ops-team", "reason": "LGTM"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["decision_at"] is not None


@pytest.mark.asyncio
async def test_decide_reject(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    resp = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "rejected"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_decide_invalid_decision_value(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    resp = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "maybe"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_decide_already_resolved_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)

    await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approved"},
        headers=auth_headers,
    )
    second = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "rejected"},
        headers=auth_headers,
    )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Email one-click token: GET/POST /v1/approvals/decide
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_decide_get_renders_confirmation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)
    token = make_decision_token(approval_id, "approved")

    resp = await client.get(f"/v1/approvals/decide?token={token}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Confirm" in resp.text


@pytest.mark.asyncio
async def test_email_decide_post_approves(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)
    token = make_decision_token(approval_id, "approved")

    resp = await client.post(f"/v1/approvals/decide?token={token}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "approved" in resp.text

    # Verify status changed
    get_resp = await client.get(f"/v1/approvals/{approval_id}", headers=auth_headers)
    assert get_resp.json()["status"] == "approved"
    assert get_resp.json()["decision_at"] is not None


@pytest.mark.asyncio
async def test_email_decide_post_rejects(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    approval_id = await _trigger_approval(client, auth_headers)
    token = make_decision_token(approval_id, "rejected")

    resp = await client.post(f"/v1/approvals/decide?token={token}")
    assert resp.status_code == 200

    get_resp = await client.get(f"/v1/approvals/{approval_id}", headers=auth_headers)
    assert get_resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_email_decide_invalid_token(client: AsyncClient) -> None:
    resp = await client.post("/v1/approvals/decide?token=bad:token:here")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_email_decide_idempotent_on_already_resolved(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Second click on an already-decided link returns 200 (not error)."""
    approval_id = await _trigger_approval(client, auth_headers)
    token = make_decision_token(approval_id, "approved")

    await client.post(f"/v1/approvals/decide?token={token}")
    second = await client.post(f"/v1/approvals/decide?token={token}")
    # Already resolved → graceful 200, not 500
    assert second.status_code == 200
    assert "already" in second.text


# ---------------------------------------------------------------------------
# Token unit tests (no HTTP needed)
# ---------------------------------------------------------------------------

def test_verify_decision_token_roundtrip() -> None:
    token = make_decision_token("some-uuid", "approved")
    result = verify_decision_token(token)
    assert result == ("some-uuid", "approved")


def test_verify_decision_token_tampered() -> None:
    token = make_decision_token("some-uuid", "approved")
    parts = token.split(":")
    parts[1] = "rejected"  # tamper the decision
    assert verify_decision_token(":".join(parts)) is None


def test_verify_decision_token_invalid_format() -> None:
    assert verify_decision_token("notavalidtoken") is None


def test_verify_decision_token_bad_decision() -> None:
    token = make_decision_token("some-uuid", "approved")
    parts = token.rsplit(":", 1)
    # Replace decision with invalid value
    inner = parts[0].split(":")
    inner[1] = "maybe"
    bad_token = ":".join(inner) + ":" + parts[1]
    assert verify_decision_token(bad_token) is None
