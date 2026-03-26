"""Integration tests for policy lifecycle states (draft → active → archived)."""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Create state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_defaults_to_draft(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/policies creates a draft policy by default."""
    resp = await client.post(
        "/v1/policies",
        json={
            "name": "Draft policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["state"] == "draft"
    assert data["active"] is False


@pytest.mark.asyncio
async def test_create_with_explicit_active_state(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/policies with state=active creates an immediately active policy."""
    resp = await client.post(
        "/v1/policies",
        json={
            "name": "Active from creation",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["state"] == "active"
    assert data["active"] is True


@pytest.mark.asyncio
async def test_create_archived_state_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/policies rejects state=archived — can't create an archived policy."""
    resp = await client.post(
        "/v1/policies",
        json={
            "name": "Bad policy",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "archived",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_draft_policy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /activate transitions draft → active."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "To activate",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
        },
        headers=auth_headers,
    )
    assert create.json()["state"] == "draft"
    policy_id = create.json()["id"]

    resp = await client.patch(
        f"/v1/policies/{policy_id}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "active"
    assert data["active"] is True


@pytest.mark.asyncio
async def test_activate_already_active_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Activating an already-active policy is a no-op (200, stays active)."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "Already active",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]

    resp = await client.patch(
        f"/v1/policies/{policy_id}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "active"


@pytest.mark.asyncio
async def test_activate_archived_policy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /activate can re-activate an archived policy."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "Re-activate me",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]

    await client.patch(f"/v1/policies/{policy_id}/archive", headers=auth_headers)

    resp = await client.patch(
        f"/v1/policies/{policy_id}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "active"
    assert resp.json()["active"] is True


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_active_policy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /archive transitions active → archived."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "To archive",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]

    resp = await client.patch(
        f"/v1/policies/{policy_id}/archive", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "archived"
    assert data["active"] is False


@pytest.mark.asyncio
async def test_archive_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Archiving an already-archived policy is a no-op."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "Archive twice",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]

    await client.patch(f"/v1/policies/{policy_id}/archive", headers=auth_headers)
    resp = await client.patch(
        f"/v1/policies/{policy_id}/archive", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "archived"


# ---------------------------------------------------------------------------
# Visibility rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_policy_not_evaluated(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Draft policies are excluded from Cedar evaluation."""
    # Create a draft permit rule for a unique action
    await client.post(
        "/v1/policies",
        json={
            "name": "Draft permit",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"draft_only_action", resource);',
            # default state=draft — NOT active
        },
        headers=auth_headers,
    )

    resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "agent-001",
            "action": "draft_only_action",
            "resource": "some-resource",
            "context": {},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    # Draft policy must not influence evaluation → no permit match → DENY
    assert resp.json()["decision"] == "DENY"


@pytest.mark.asyncio
async def test_archived_policy_excluded_from_get(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /v1/policies/{id} returns 404 for archived policies."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "Soon archived",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]

    await client.patch(f"/v1/policies/{policy_id}/archive", headers=auth_headers)

    get_resp = await client.get(f"/v1/policies/{policy_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_filter_by_state(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /v1/policies?state= filters correctly."""
    # Create one draft and one active
    await client.post(
        "/v1/policies",
        json={
            "name": "State filter draft",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"s1", resource);',
        },
        headers=auth_headers,
    )
    await client.post(
        "/v1/policies",
        json={
            "name": "State filter active",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"s2", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )

    draft_resp = await client.get("/v1/policies?state=draft", headers=auth_headers)
    assert draft_resp.status_code == 200
    draft_names = [p["name"] for p in draft_resp.json()]
    assert "State filter draft" in draft_names
    assert "State filter active" not in draft_names

    active_resp = await client.get("/v1/policies?state=active", headers=auth_headers)
    assert active_resp.status_code == 200
    active_names = [p["name"] for p in active_resp.json()]
    assert "State filter active" in active_names
    assert "State filter draft" not in active_names


@pytest.mark.asyncio
async def test_archived_policy_not_updatable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH on an archived policy returns 404 (use /activate to restore)."""
    create = await client.post(
        "/v1/policies",
        json={
            "name": "Freeze me",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"read", resource);',
            "state": "active",
        },
        headers=auth_headers,
    )
    policy_id = create.json()["id"]
    await client.patch(f"/v1/policies/{policy_id}/archive", headers=auth_headers)

    patch_resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"name": "New name"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 404


@pytest.mark.asyncio
async def test_response_includes_state_field(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """All PolicyResponse objects include the state field."""
    list_resp = await client.get("/v1/policies", headers=auth_headers)
    assert list_resp.status_code == 200
    for policy in list_resp.json():
        assert "state" in policy
        assert policy["state"] in ("draft", "active", "archived")
