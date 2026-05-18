"""Unit tests for the W5.5 behavioural anomaly advisory.

Exercises the pure logic (score calculation, threshold gating, finding
shape) with a stub Redis client. Wiring into the evaluate route is
covered by the integration suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from app.services import anomaly_service


class _StubRedis:
    """Minimal Redis fake covering only the methods anomaly_service touches."""

    def __init__(self, members: dict[str, float] | None = None) -> None:
        self._members: dict[str, float] = dict(members or {})

    async def zscore(self, _key: str, member: str) -> float | None:
        return self._members.get(member)

    async def zrange(
        self, _key: str, _start: int, _stop: int, withscores: bool = False
    ) -> list[tuple[str, float]]:
        assert withscores is True
        return list(self._members.items())

    async def zincrby(self, _key: str, amount: float, member: str) -> float:
        new = self._members.get(member, 0.0) + amount
        self._members[member] = new
        return new

    async def expire(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


def _patch_redis(stub: _StubRedis | None) -> Any:
    return patch.object(
        anomaly_service,
        "get_redis_client",
        return_value=stub,
    )


@pytest.mark.asyncio
async def test_triple_anomaly_score_returns_zero_when_redis_unavailable() -> None:
    with _patch_redis(None):
        score = await anomaly_service.triple_anomaly_score("o", "a", "deploy", "prod")
    assert score == 0.0


@pytest.mark.asyncio
async def test_triple_anomaly_score_returns_zero_when_baseline_too_thin() -> None:
    # Only 5 total observations — below _MIN_BASELINE_SAMPLES (20).
    stub = _StubRedis(members={"deploy::prod": 5.0})
    with _patch_redis(stub):
        score = await anomaly_service.triple_anomaly_score("o", "a", "transfer", "vault")
    assert score == 0.0


@pytest.mark.asyncio
async def test_triple_anomaly_score_high_for_novel_triple() -> None:
    stub = _StubRedis(
        members={
            "read::doc": 60.0,
            "list::doc": 40.0,
        }
    )
    with _patch_redis(stub):
        score = await anomaly_service.triple_anomaly_score("o", "a", "delete", "vault")
    # Novel triple → count=0, total=100 → score = 1.0
    assert score == 1.0


@pytest.mark.asyncio
async def test_triple_anomaly_score_low_for_dominant_triple() -> None:
    stub = _StubRedis(
        members={
            "read::doc": 95.0,
            "list::doc": 5.0,
        }
    )
    with _patch_redis(stub):
        score = await anomaly_service.triple_anomaly_score("o", "a", "read", "doc")
    # Dominant triple → 1 - 0.95 = 0.05
    assert score == pytest.approx(0.05, abs=1e-6)


@pytest.mark.asyncio
async def test_behavioral_anomaly_finding_none_below_threshold() -> None:
    fake = AsyncMock(return_value=0.5)
    with patch.object(anomaly_service, "triple_anomaly_score", fake):
        finding = await anomaly_service.behavioral_anomaly_finding("o", "a", "read", "doc")
    assert finding is None


@pytest.mark.asyncio
async def test_behavioral_anomaly_finding_emits_info_finding_when_breached() -> None:
    fake = AsyncMock(return_value=0.9)
    with patch.object(anomaly_service, "triple_anomaly_score", fake):
        finding = await anomaly_service.behavioral_anomaly_finding(
            "o", "agent_x", "delete", "vault"
        )
    assert finding is not None
    assert finding["plugin"] == "behavioral_anomaly"
    assert finding["severity"] == "info"
    assert finding["passed"] is True
    assert finding["standard"] == "INTERNAL"
    # Message must contain the triple so audit consumers can spot the cause.
    assert "agent_x" in str(finding["message"])
    assert "delete" in str(finding["message"])
    assert "vault" in str(finding["message"])


@pytest.mark.asyncio
async def test_record_triple_increments_member() -> None:
    stub = _StubRedis(members={"deploy::prod": 2.0})
    with _patch_redis(stub):
        await anomaly_service.record_triple("o", "a", "deploy", "prod")
    assert stub._members["deploy::prod"] == 3.0


@pytest.mark.asyncio
async def test_record_triple_swallows_redis_unavailable() -> None:
    # Must not raise when Redis is None.
    with _patch_redis(None):
        await anomaly_service.record_triple("o", "a", "deploy", "prod")
