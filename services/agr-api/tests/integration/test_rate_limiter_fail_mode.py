"""W3.3 — Rate limiter fail-mode behaviour when Redis is unreachable."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fail_open_allows_request_when_redis_unavailable(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.middleware.rate_limiter as rate_limiter_module
    from app.config import settings
    from app.services.redis_service import RateLimitResult

    async def fake_check(_r, _org, _limit, _burst):  # noqa: ANN001
        return RateLimitResult(allowed=True, remaining=99, reset_at=1.0, redis_available=False)

    monkeypatch.setattr(rate_limiter_module, "check_rate_limit", fake_check)
    monkeypatch.setattr(settings, "rate_limit_fail_mode", "open")

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    # Either ALLOW or APPROVAL_REQUIRED is fine — the contract is "not 503".
    assert response.status_code != 503


@pytest.mark.asyncio
async def test_fail_closed_returns_503_when_redis_unavailable(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.middleware.rate_limiter as rate_limiter_module
    from app.config import settings
    from app.services.redis_service import RateLimitResult

    async def fake_check(_r, _org, _limit, _burst):  # noqa: ANN001
        return RateLimitResult(allowed=True, remaining=99, reset_at=1.0, redis_available=False)

    monkeypatch.setattr(rate_limiter_module, "check_rate_limit", fake_check)
    monkeypatch.setattr(settings, "rate_limit_fail_mode", "closed")

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "5"
    assert response.json()["error"] == "rate_limit_unavailable"
