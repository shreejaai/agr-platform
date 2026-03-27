"""Integration tests for GET /v1/org/me."""

import pytest
from app.models import Organization
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_org_me(client: AsyncClient, auth_headers: dict, test_org: Organization) -> None:
    resp = await client.get("/v1/org/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_org.id)
    assert data["name"] == test_org.name
    assert data["plan"] == test_org.plan
    assert data["eval_count"] == test_org.eval_count
    assert data["eval_limit"] == test_org.eval_limit
    assert data["auth_mode"] == "api_key"
    assert data["sso_enabled"] is False


@pytest.mark.asyncio
async def test_get_org_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/v1/org/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_org_me_wrong_key(client: AsyncClient) -> None:
    resp = await client.get("/v1/org/me", headers={"Authorization": "Bearer agr_sk_invalid"})
    assert resp.status_code == 401
