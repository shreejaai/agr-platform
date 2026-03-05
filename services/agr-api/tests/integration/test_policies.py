"""Integration tests for policy CRUD."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_policies(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/v1/policies", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3


@pytest.mark.asyncio
async def test_create_policy(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/v1/policies",
        json={
            "name": "Custom policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Custom policy"
    assert data["version"] == 1
    assert data["active"] is True


@pytest.mark.asyncio
async def test_update_policy_increments_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Create
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Versioned policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"v1", resource);',
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    # Update cedar_rule → version should increment
    update_resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2


@pytest.mark.asyncio
async def test_toggle_policy_active(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Toggle policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"test", resource);',
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"active": False},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["active"] is False


@pytest.mark.asyncio
async def test_delete_policy(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "Delete me",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"del", resource);',
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/v1/policies/{policy_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/v1/policies/{policy_id}", headers=auth_headers)
    assert get_resp.status_code == 404
