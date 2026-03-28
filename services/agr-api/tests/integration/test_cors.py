import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_wildcard_cors_preflight_returns_star_without_credentials(
    client: AsyncClient,
) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "https://dashboard.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.headers["Access-Control-Allow-Headers"] == "Authorization"
    assert "Access-Control-Allow-Credentials" not in response.headers


@pytest.mark.asyncio
async def test_wildcard_cors_simple_request_returns_star_without_credentials(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/health",
        headers={"Origin": "https://dashboard.example.com"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response.headers
