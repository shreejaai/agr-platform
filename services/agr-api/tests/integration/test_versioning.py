import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_version_metadata_endpoint_returns_expected_payload(client: AsyncClient) -> None:
    response = await client.get("/v1/meta")

    assert response.status_code == 200
    assert response.headers["AGR-API-Version"] == "v1"
    assert response.json() == {
        "api_version": "v1",
        "min_supported_version": "v1",
        "deprecated_versions": [],
        "latest_version": "v1",
        "changelog_url": "https://docs.agr.dev/changelog",
    }
