import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rate_limiter_returns_429_on_51st_request(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.middleware.rate_limiter as rate_limiter_module
    from app.services.redis_service import RateLimitResult

    counter = {"count": 0}

    async def fake_check_rate_limit(redis_client, org_id, limit, burst):  # noqa: ANN001
        counter["count"] += 1
        if counter["count"] <= 50:
            return RateLimitResult(allowed=True, remaining=max(0, 50 - counter["count"]), reset_at=1.0)
        return RateLimitResult(allowed=False, remaining=0, reset_at=2.0, retry_after=0.5)

    monkeypatch.setattr(rate_limiter_module, "check_rate_limit", fake_check_rate_limit)

    last_response = None
    for _ in range(51):
        last_response = await client.post(
            "/v1/evaluate",
            json={
                "agent_id": "coder-001",
                "action": "deploy",
                "resource": "staging-server",
                "context": {"environment": "staging"},
            },
            headers=auth_headers,
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert last_response.headers["Retry-After"] == "0.5"


@pytest.mark.asyncio
async def test_rate_limiter_sets_retry_after_header(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.middleware.rate_limiter as rate_limiter_module
    from app.services.redis_service import RateLimitResult

    async def fake_check_rate_limit(redis_client, org_id, limit, burst):  # noqa: ANN001
        return RateLimitResult(allowed=False, remaining=0, reset_at=123.5, retry_after=1.25)

    monkeypatch.setattr(rate_limiter_module, "check_rate_limit", fake_check_rate_limit)

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1.25"
    assert response.headers["X-RateLimit-Remaining"] == "0"
