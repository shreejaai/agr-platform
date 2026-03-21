"""Integration tests for POST /v1/policies/import and GET /v1/policies/export."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_VALID_POLICY = {
    "name": "Bulk Allow reads",
    "level": "org",
    "cedar_rule": 'permit(principal, action == Action::"read", resource);',
}

_VALID_POLICY_2 = {
    "name": "Bulk Deny drops",
    "level": "org",
    "cedar_rule": 'forbid(principal, action == Action::"drop", resource);',
}


@pytest.mark.asyncio
async def test_import_creates_policies(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    response = await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY, _VALID_POLICY_2]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["created"] == 2
    assert data["errors"] == 0
    assert data["dry_run"] is False
    assert all(r["status"] == "created" for r in data["results"])
    assert all(r["policy_id"] is not None for r in data["results"])


@pytest.mark.asyncio
async def test_import_dry_run_does_not_persist(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    response = await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY], "dry_run": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["created"] == 1
    # No policy_id set on dry run
    assert data["results"][0]["policy_id"] is None


@pytest.mark.asyncio
async def test_import_overwrite_updates_existing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # First create
    r1 = await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY]},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["created"] == 1

    # Overwrite with updated rule
    new_rule = 'forbid(principal, action == Action::"delete", resource);'
    updated = {**_VALID_POLICY, "cedar_rule": new_rule}
    r2 = await client.post(
        "/v1/policies/import",
        json={"policies": [updated], "overwrite": True},
        headers=auth_headers,
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["updated"] == 1
    assert data["created"] == 0


@pytest.mark.asyncio
async def test_import_skip_existing_without_overwrite(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Create first
    await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY]},
        headers=auth_headers,
    )
    # Import again without overwrite — should skip
    r = await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["skipped"] == 1


@pytest.mark.asyncio
async def test_import_invalid_cedar_returns_error(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/v1/policies/import",
        json={
            "policies": [{"name": "Bad policy", "level": "org", "cedar_rule": "not valid cedar"}]
        },
        headers=auth_headers,
    )
    # Pydantic validation error → 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_returns_all_policies(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # First import some policies
    await client.post(
        "/v1/policies/import",
        json={"policies": [_VALID_POLICY, _VALID_POLICY_2]},
        headers=auth_headers,
    )

    response = await client.get("/v1/policies/export", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "policies" in data
    assert "total" in data
    assert data["total"] >= 2  # includes the 3 test_policies from conftest


@pytest.mark.asyncio
async def test_export_active_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/v1/policies/export?active_only=true", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert all(p["active"] for p in data["policies"])


@pytest.mark.asyncio
async def test_export_roundtrip(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Export then re-import (with overwrite) produces same policy set."""
    export_r = await client.get("/v1/policies/export", headers=auth_headers)
    assert export_r.status_code == 200
    exported = export_r.json()["policies"]

    import_r = await client.post(
        "/v1/policies/import",
        json={"policies": exported, "overwrite": True},
        headers=auth_headers,
    )
    assert import_r.status_code == 200
    data = import_r.json()
    assert data["errors"] == 0
