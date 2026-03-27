"""Integration tests for the policy template library."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_policy_templates(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/v1/policies/templates", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    assert {item["id"] for item in data} >= {
        "safe-api-access",
        "restricted-data-access",
        "approval-required-actions",
    }
    assert all(item["policies"] for item in data)


@pytest.mark.asyncio
async def test_import_template_payload_from_dashboard_flow(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    templates_response = await client.get("/v1/policies/templates", headers=auth_headers)
    assert templates_response.status_code == 200
    template = next(
        item for item in templates_response.json() if item["id"] == "approval-required-actions"
    )

    import_response = await client.post(
        "/v1/policies/import",
        json={"policies": template["policies"], "overwrite": True, "dry_run": True},
        headers=auth_headers,
    )

    assert import_response.status_code == 200
    data = import_response.json()
    assert data["dry_run"] is True
    assert data["total"] == len(template["policies"])
    assert data["created"] == len(template["policies"])
