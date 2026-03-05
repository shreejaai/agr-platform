"""Integration tests for approval flow."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_approval_flow_evaluate_approve(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Full flow: evaluate → APPROVAL_REQUIRED → approve → status=approved."""
    # Evaluate to trigger approval
    eval_resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "APPROVAL_REQUIRED"
    approval_id = eval_resp.json()["approval_id"]

    # List pending approvals
    list_resp = await client.get(
        "/v1/approvals", params={"status": "pending"}, headers=auth_headers
    )
    assert list_resp.status_code == 200
    approvals = list_resp.json()
    assert any(a["id"] == approval_id for a in approvals)

    # Approve
    approve_resp = await client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={"decided_by": "test-user", "reason": "Looks good"},
        headers=auth_headers,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_approval_reject(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    eval_resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    approval_id = eval_resp.json()["approval_id"]

    reject_resp = await client.post(
        f"/v1/approvals/{approval_id}/reject",
        json={"decided_by": "test-user", "reason": "Not ready"},
        headers=auth_headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_approval_double_approve_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    eval_resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    approval_id = eval_resp.json()["approval_id"]

    await client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={},
        headers=auth_headers,
    )
    # Second approve should fail
    second_resp = await client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={},
        headers=auth_headers,
    )
    assert second_resp.status_code == 409
