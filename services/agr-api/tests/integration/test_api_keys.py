from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_scoped_api_key_returns_full_key_once(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/org/api_keys",
        json={"name": "CI key", "scopes": ["evaluate:write"]},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["key"].startswith("agr_sk_")
    assert data["key_prefix"].startswith("agr_sk_")
    assert data["scopes"] == ["evaluate:write"]


@pytest.mark.asyncio
async def test_evaluate_only_key_is_blocked_from_reading_policies(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create = await client.post(
        "/v1/org/api_keys",
        json={"name": "Eval key", "scopes": ["evaluate:write"]},
        headers=auth_headers,
    )
    scoped_headers = {"Authorization": f"Bearer {create.json()['key']}"}

    response = await client.get("/v1/policies", headers=scoped_headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_policies_read_key_can_list_policies(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create = await client.post(
        "/v1/org/api_keys",
        json={"name": "Policies read", "scopes": ["policies:read"]},
        headers=auth_headers,
    )
    scoped_headers = {"Authorization": f"Bearer {create.json()['key']}"}

    response = await client.get("/v1/policies", headers=scoped_headers)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_revoked_key_returns_401(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post(
        "/v1/org/api_keys",
        json={"name": "Revoked", "scopes": ["policies:read"]},
        headers=auth_headers,
    )
    key_id = create.json()["id"]
    scoped_headers = {"Authorization": f"Bearer {create.json()['key']}"}

    revoke = await client.delete(f"/v1/org/api_keys/{key_id}", headers=auth_headers)
    assert revoke.status_code == 204

    response = await client.get("/v1/policies", headers=scoped_headers)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_key_returns_401(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/v1/org/api_keys",
        json={
            "name": "Expired",
            "scopes": ["policies:read"],
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers,
    )
    scoped_headers = {"Authorization": f"Bearer {response.json()['key']}"}

    denied = await client.get("/v1/policies", headers=scoped_headers)

    assert denied.status_code == 401
