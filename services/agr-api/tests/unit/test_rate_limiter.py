import pytest
from app.services.redis_service import RateLimitResult, check_rate_limit


class _FakeRedis:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, float]] = {}

    async def eval(self, script, numkeys, key, now, limit, burst):  # noqa: ANN001
        bucket = self.buckets.get(key)
        current = float(now)
        refill_rate = float(limit)
        capacity = float(burst)
        if bucket is None:
            tokens = capacity
            timestamp = current
        else:
            tokens = bucket["tokens"]
            timestamp = bucket["timestamp"]

        delta = max(0.0, current - timestamp)
        tokens = min(capacity, tokens + delta * refill_rate)

        allowed = 0
        retry_after = 0.0
        if tokens >= 1.0:
            allowed = 1
            tokens -= 1.0
        else:
            retry_after = (1.0 - tokens) / refill_rate

        self.buckets[key] = {"tokens": tokens, "timestamp": current}
        return [allowed, tokens, current + retry_after, retry_after]


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_then_throttles(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    current = [100.0]
    monkeypatch.setattr("app.services.redis_service.time.time", lambda: current[0])

    first = await check_rate_limit(fake_redis, "org-1", limit=2, burst=3)
    second = await check_rate_limit(fake_redis, "org-1", limit=2, burst=3)
    third = await check_rate_limit(fake_redis, "org-1", limit=2, burst=3)
    fourth = await check_rate_limit(fake_redis, "org-1", limit=2, burst=3)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is True
    assert fourth.allowed is False
    assert fourth.retry_after is not None


@pytest.mark.asyncio
async def test_token_bucket_refills_at_expected_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    current = [100.0]
    monkeypatch.setattr("app.services.redis_service.time.time", lambda: current[0])

    await check_rate_limit(fake_redis, "org-1", limit=1, burst=1)
    blocked = await check_rate_limit(fake_redis, "org-1", limit=1, burst=1)
    assert blocked.allowed is False

    current[0] += 1.1
    refilled = await check_rate_limit(fake_redis, "org-1", limit=1, burst=1)

    assert refilled.allowed is True
    assert isinstance(refilled, RateLimitResult)
