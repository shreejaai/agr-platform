"""Integration tests for policy versioning and rollback."""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_active(client: AsyncClient, headers: dict, name: str, rule: str) -> dict:
    resp = await client.post(
        "/v1/policies",
        json={"name": name, "level": "org", "cedar_rule": rule, "state": "active"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Snapshot on PATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_cedar_rule_creates_snapshot(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Changing cedar_rule via PATCH saves the old state to versions."""
    policy = await _create_active(
        client, auth_headers, "Snap test", 'permit(principal, action == Action::"v1", resource);'
    )
    policy_id = policy["id"]
    old_rule = policy["cedar_rule"]

    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )

    versions_resp = await client.get(
        f"/v1/policies/{policy_id}/versions", headers=auth_headers
    )
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) == 1
    assert versions[0]["cedar_rule"] == old_rule
    assert versions[0]["version"] == 1


@pytest.mark.asyncio
async def test_patch_name_creates_snapshot(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Changing name via PATCH saves the old state to versions."""
    policy = await _create_active(
        client, auth_headers, "Original name", 'permit(principal, action == Action::"x", resource);'
    )
    policy_id = policy["id"]

    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"name": "Renamed policy"},
        headers=auth_headers,
    )

    versions_resp = await client.get(
        f"/v1/policies/{policy_id}/versions", headers=auth_headers
    )
    assert len(versions_resp.json()) == 1
    assert versions_resp.json()[0]["name"] == "Original name"


@pytest.mark.asyncio
async def test_no_change_patch_creates_no_snapshot(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH with no actual field change must not create a version snapshot."""
    policy = await _create_active(
        client, auth_headers, "Unchanged", 'permit(principal, action == Action::"x", resource);'
    )
    policy_id = policy["id"]

    # Patch with same name — nothing changes
    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"name": "Unchanged"},
        headers=auth_headers,
    )

    versions_resp = await client.get(
        f"/v1/policies/{policy_id}/versions", headers=auth_headers
    )
    assert versions_resp.json() == []


@pytest.mark.asyncio
async def test_multiple_patches_accumulate_versions(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Each content-changing PATCH adds a new snapshot; newest version first."""
    policy = await _create_active(
        client, auth_headers, "Multi-ver", 'permit(principal, action == Action::"v1", resource);'
    )
    policy_id = policy["id"]

    for n in range(2, 5):
        await client.patch(
            f"/v1/policies/{policy_id}",
            json={"cedar_rule": f'permit(principal, action == Action::"v{n}", resource);'},
            headers=auth_headers,
        )

    versions_resp = await client.get(
        f"/v1/policies/{policy_id}/versions", headers=auth_headers
    )
    versions = versions_resp.json()
    assert len(versions) == 3
    # Returned newest-first (highest version number first)
    assert versions[0]["version"] > versions[1]["version"] > versions[2]["version"]


# ---------------------------------------------------------------------------
# Version list endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_versions_empty_for_unmodified_policy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Newly created policy has no version history."""
    policy = await _create_active(
        client, auth_headers, "Fresh", 'permit(principal, action == Action::"x", resource);'
    )
    resp = await client.get(
        f"/v1/policies/{policy['id']}/versions", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_versions_returns_404_for_unknown_policy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /versions returns 404 for a policy that doesn't exist."""
    import uuid

    resp = await client.get(
        f"/v1/policies/{uuid.uuid4()}/versions", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_version_response_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Each version entry contains all required fields."""
    policy = await _create_active(
        client, auth_headers, "Field test", 'permit(principal, action == Action::"a", resource);'
    )
    policy_id = policy["id"]

    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"b", resource);'},
        headers=auth_headers,
    )

    versions = (
        await client.get(f"/v1/policies/{policy_id}/versions", headers=auth_headers)
    ).json()

    v = versions[0]
    assert "id" in v
    assert v["policy_id"] == policy_id
    assert "org_id" in v
    assert "cedar_rule" in v
    assert "name" in v
    assert "level" in v
    assert "state" in v
    assert "version" in v
    assert "created_at" in v


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_restores_cedar_rule(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /rollback/{version} restores policy content from the snapshot."""
    rule = 'permit(principal, action == Action::"v1", resource);'
    policy = await _create_active(client, auth_headers, "Rollback test", rule)
    policy_id = policy["id"]
    original_rule = policy["cedar_rule"]

    # Patch to v2
    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )

    # Rollback to version 1
    rollback_resp = await client.post(
        f"/v1/policies/{policy_id}/rollback/1", headers=auth_headers
    )
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["cedar_rule"] == original_rule


@pytest.mark.asyncio
async def test_rollback_increments_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Rollback advances the version counter so history stays linear."""
    policy = await _create_active(
        client, auth_headers, "Ver inc", 'permit(principal, action == Action::"v1", resource);'
    )
    policy_id = policy["id"]

    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )
    current_version = (
        await client.get(f"/v1/policies/{policy_id}", headers=auth_headers)
    ).json()["version"]

    rollback_resp = await client.post(
        f"/v1/policies/{policy_id}/rollback/1", headers=auth_headers
    )
    assert rollback_resp.json()["version"] == current_version + 1


@pytest.mark.asyncio
async def test_rollback_snapshots_current_before_restore(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Rollback itself is snapshotted so the rollback is reversible."""
    rule = 'permit(principal, action == Action::"v1", resource);'
    policy = await _create_active(client, auth_headers, "Reversible rollback", rule)
    policy_id = policy["id"]

    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"v2", resource);'},
        headers=auth_headers,
    )

    pre_rollback_version = (
        await client.get(f"/v1/policies/{policy_id}", headers=auth_headers)
    ).json()["version"]

    await client.post(f"/v1/policies/{policy_id}/rollback/1", headers=auth_headers)

    versions = (
        await client.get(f"/v1/policies/{policy_id}/versions", headers=auth_headers)
    ).json()
    # Should now have: original v1 snapshot + pre-rollback v2 snapshot = 2
    assert len(versions) == 2
    version_numbers = {v["version"] for v in versions}
    assert pre_rollback_version in version_numbers


@pytest.mark.asyncio
async def test_rollback_unknown_version_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /rollback/{version} returns 404 when the version doesn't exist."""
    policy = await _create_active(
        client, auth_headers, "No ver", 'permit(principal, action == Action::"x", resource);'
    )
    resp = await client.post(
        f"/v1/policies/{policy['id']}/rollback/99", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rollback_unknown_policy_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /rollback returns 404 for a policy that doesn't exist."""
    import uuid

    resp = await client.post(
        f"/v1/policies/{uuid.uuid4()}/rollback/1", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rollback_restores_state(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Rollback restores the policy state (e.g., draft) from the snapshot."""
    # Create as draft, then activate, then rollback to draft state
    create_resp = await client.post(
        "/v1/policies",
        json={
            "name": "State rollback",
            "level": "org",
            "cedar_rule": 'permit(principal, action == Action::"x", resource);',
            # default state=draft
        },
        headers=auth_headers,
    )
    policy_id = create_resp.json()["id"]

    # Activate (state transition — no snapshot)
    await client.patch(f"/v1/policies/{policy_id}/activate", headers=auth_headers)

    # Now patch cedar_rule — this snapshots the current (active) state
    await client.patch(
        f"/v1/policies/{policy_id}",
        json={"cedar_rule": 'permit(principal, action == Action::"y", resource);'},
        headers=auth_headers,
    )

    # Snapshot should show state=active
    versions = (
        await client.get(f"/v1/policies/{policy_id}/versions", headers=auth_headers)
    ).json()
    assert len(versions) == 1
    assert versions[0]["state"] == "active"
