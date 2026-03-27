"""Integration tests for /v1/org/members — team invite and role management."""

import pytest
from app.models import Organization
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_members_empty(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """List returns empty array for a fresh org."""
    resp = await client.get("/v1/org/members", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_invite_member_requires_admin(
    client: AsyncClient, auth_headers: dict[str, str], test_org: Organization
) -> None:
    """Inviting requires admin role; test org defaults to admin so this should succeed."""
    assert test_org.role == "admin"
    resp = await client.post(
        "/v1/org/members/invite",
        json={"email": "alice@example.com", "role": "viewer"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "viewer"
    assert data["status"] == "invited"


@pytest.mark.asyncio
async def test_invite_member_duplicate_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Inviting the same email twice returns 409."""
    payload = {"email": "bob@example.com", "role": "operator"}
    r1 = await client.post("/v1/org/members/invite", json=payload, headers=auth_headers)
    assert r1.status_code == 201
    r2 = await client.post("/v1/org/members/invite", json=payload, headers=auth_headers)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error"] == "already_invited"


@pytest.mark.asyncio
async def test_list_members_after_invite(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """After invite, the member appears in the list."""
    await client.post(
        "/v1/org/members/invite",
        json={"email": "charlie@example.com", "role": "admin"},
        headers=auth_headers,
    )
    resp = await client.get("/v1/org/members", headers=auth_headers)
    assert resp.status_code == 200
    emails = [m["email"] for m in resp.json()]
    assert "charlie@example.com" in emails


@pytest.mark.asyncio
async def test_update_member_role(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Patch updates the member role."""
    invite_resp = await client.post(
        "/v1/org/members/invite",
        json={"email": "dave@example.com", "role": "viewer"},
        headers=auth_headers,
    )
    assert invite_resp.status_code == 201
    member_id = invite_resp.json()["id"]

    patch_resp = await client.patch(
        f"/v1/org/members/{member_id}",
        json={"role": "operator"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["role"] == "operator"


@pytest.mark.asyncio
async def test_revoke_member(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Revoke sets status to revoked."""
    invite_resp = await client.post(
        "/v1/org/members/invite",
        json={"email": "eve@example.com", "role": "viewer"},
        headers=auth_headers,
    )
    assert invite_resp.status_code == 201
    member_id = invite_resp.json()["id"]

    del_resp = await client.delete(
        f"/v1/org/members/{member_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # After revoke, member still in list with revoked status
    list_resp = await client.get("/v1/org/members", headers=auth_headers)
    member = next((m for m in list_resp.json() if m["id"] == member_id), None)
    assert member is not None
    assert member["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_already_revoked_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Revoking a revoked member returns 409."""
    invite_resp = await client.post(
        "/v1/org/members/invite",
        json={"email": "frank@example.com", "role": "viewer"},
        headers=auth_headers,
    )
    member_id = invite_resp.json()["id"]
    await client.delete(f"/v1/org/members/{member_id}", headers=auth_headers)
    resp2 = await client.delete(f"/v1/org/members/{member_id}", headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_update_nonexistent_member_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Patching a non-existent member_id returns 404."""
    import uuid

    resp = await client.patch(
        f"/v1/org/members/{uuid.uuid4()}",
        json={"role": "admin"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
