"""Integration tests for webhook CRUD endpoints."""

import uuid

import pytest
from app.models import Organization
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_webhook(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["approval.approved"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com/hook"
    assert data["events"] == ["approval.approved"]
    assert data["active"] is True
    assert data["secret"].startswith("agr_wh_")
    assert len(data["secret"]) > 10
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_webhook_both_events(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/v1/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["approval.approved", "approval.rejected"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert set(resp.json()["events"]) == {"approval.approved", "approval.rejected"}


@pytest.mark.asyncio
async def test_create_webhook_invalid_event(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["unknown.event"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_webhook_default_events(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert set(resp.json()["events"]) == {"approval.approved", "approval.rejected"}


@pytest.mark.asyncio
async def test_list_webhooks(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await client.post(
        "/v1/webhooks", json={"url": "https://example.com/hook1"}, headers=auth_headers
    )
    await client.post(
        "/v1/webhooks", json={"url": "https://example.com/hook2"}, headers=auth_headers
    )

    resp = await client.get("/v1/webhooks", headers=auth_headers)
    assert resp.status_code == 200
    urls = [w["url"] for w in resp.json()]
    assert "https://example.com/hook1" in urls
    assert "https://example.com/hook2" in urls


@pytest.mark.asyncio
async def test_get_webhook_by_id(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/webhooks", json={"url": "https://example.com/hook"}, headers=auth_headers
    )
    wh_id = create_resp.json()["id"]

    resp = await client.get(f"/v1/webhooks/{wh_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == wh_id
    assert resp.json()["url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_get_webhook_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.get(f"/v1/webhooks/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_webhook(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create_resp = await client.post(
        "/v1/webhooks", json={"url": "https://example.com/hook"}, headers=auth_headers
    )
    wh_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/v1/webhooks/{wh_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/v1/webhooks/{wh_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_webhook_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.delete(f"/v1/webhooks/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_each_webhook_has_unique_secret(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r1 = await client.post(
        "/v1/webhooks", json={"url": "https://a.example.com/hook"}, headers=auth_headers
    )
    r2 = await client.post(
        "/v1/webhooks", json={"url": "https://b.example.com/hook"}, headers=auth_headers
    )
    assert r1.json()["secret"] != r2.json()["secret"]


@pytest.mark.asyncio
async def test_webhooks_isolated_between_orgs(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org_b: Organization,
) -> None:
    create_resp = await client.post(
        "/v1/webhooks", json={"url": "https://example.com/hook"}, headers=auth_headers
    )
    wh_id = create_resp.json()["id"]

    headers_b = {"Authorization": f"Bearer {test_org_b.api_key}"}

    # Org B should not see org A's webhook in list
    list_resp = await client.get("/v1/webhooks", headers=headers_b)
    assert list_resp.status_code == 200
    assert all(w["id"] != wh_id for w in list_resp.json())

    # Org B should get 404 on org A's webhook
    get_resp = await client.get(f"/v1/webhooks/{wh_id}", headers=headers_b)
    assert get_resp.status_code == 404

    # Org B cannot delete org A's webhook
    del_resp = await client.delete(f"/v1/webhooks/{wh_id}", headers=headers_b)
    assert del_resp.status_code == 404


@pytest.mark.asyncio
async def test_webhooks_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/v1/webhooks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_retry_delivery_requires_admin_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    test_org.role = "operator"
    await db_session.commit()

    resp = await client.post(
        f"/v1/webhooks/{uuid.uuid4()}/deliveries/{uuid.uuid4()}/retry",
        headers=auth_headers,
    )
    assert resp.status_code == 403
