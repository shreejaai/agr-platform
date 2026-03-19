"""Integration tests for agent registration and listing."""

import pytest
from app.models import Organization
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# POST /v1/agents/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_agent_persists_to_db(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001", "metadata": {"framework": "langgraph"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "coder-001"
    assert data["metadata"] == {"framework": "langgraph"}
    assert "id" in data
    assert "org_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_register_agent_upserts_metadata(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # First registration
    resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001", "metadata": {"version": "1"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    first_id = resp.json()["id"]

    # Re-register same agent_id with new metadata
    resp2 = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001", "metadata": {"version": "2"}},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    data = resp2.json()
    # Same DB row — same id
    assert data["id"] == first_id
    # Metadata updated
    assert data["metadata"]["version"] == "2"


@pytest.mark.asyncio
async def test_register_agent_empty_metadata(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "minimal-agent"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {}


@pytest.mark.asyncio
async def test_register_agent_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_agent_org_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org_b: Organization,
) -> None:
    """Agent registered under org A must not appear in org B's list."""
    await client.post(
        "/v1/agents/register",
        json={"agent_id": "shared-name", "metadata": {"owner": "org-a"}},
        headers=auth_headers,
    )

    headers_b = {"Authorization": f"Bearer {test_org_b.api_key}"}
    resp = await client.get("/v1/agents", headers=headers_b)
    assert resp.status_code == 200
    agent_ids = [a["agent_id"] for a in resp.json()]
    assert "shared-name" not in agent_ids


# ---------------------------------------------------------------------------
# GET /v1/agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_empty(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.get("/v1/agents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_agents_returns_registered(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for name in ("agent-a", "agent-b", "agent-c"):
        await client.post(
            "/v1/agents/register",
            json={"agent_id": name},
            headers=auth_headers,
        )

    resp = await client.get("/v1/agents", headers=auth_headers)
    assert resp.status_code == 200
    ids = [a["agent_id"] for a in resp.json()]
    assert set(ids) == {"agent-a", "agent-b", "agent-c"}


@pytest.mark.asyncio
async def test_list_agents_all_present(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    for name in ("first", "second", "third"):
        await client.post(
            "/v1/agents/register",
            json={"agent_id": name},
            headers=auth_headers,
        )

    resp = await client.get("/v1/agents", headers=auth_headers)
    assert resp.status_code == 200
    ids = {a["agent_id"] for a in resp.json()}
    assert ids == {"first", "second", "third"}


@pytest.mark.asyncio
async def test_list_agents_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/v1/agents")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/agents/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_by_id(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    register_resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001", "metadata": {"env": "prod"}},
        headers=auth_headers,
    )
    agent_uuid = register_resp.json()["id"]

    resp = await client.get(f"/v1/agents/{agent_uuid}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_uuid
    assert data["agent_id"] == "coder-001"
    assert data["metadata"] == {"env": "prod"}


@pytest.mark.asyncio
async def test_get_agent_by_id_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    import uuid

    resp = await client.get(f"/v1/agents/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_agent_by_id_wrong_org(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org_b: Organization,
) -> None:
    """Org B cannot fetch an agent that belongs to org A."""
    register_resp = await client.post(
        "/v1/agents/register",
        json={"agent_id": "coder-001"},
        headers=auth_headers,
    )
    agent_uuid = register_resp.json()["id"]

    headers_b = {"Authorization": f"Bearer {test_org_b.api_key}"}
    resp = await client.get(f"/v1/agents/{agent_uuid}", headers=headers_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Unit: seed_default_policies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_default_policies(db_session: AsyncSession, test_org: Organization) -> None:
    from app.services.org_service import seed_default_policies

    policies = await seed_default_policies(db_session, test_org.id)
    await db_session.commit()

    seeded_names = {p.name for p in policies}
    assert "Block production DB drops" in seeded_names
    assert "Require approval for production deploys" in seeded_names
    assert "Block writes to secrets/env files" in seeded_names
    assert "Allow staging auto-deploy" in seeded_names
    assert "Allow source code writes" in seeded_names
    assert len(policies) == 5
    for p in policies:
        assert p.org_id == test_org.id
        assert p.level == "org"
        assert p.active is True
