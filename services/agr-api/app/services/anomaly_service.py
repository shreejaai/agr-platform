"""Redis-backed agent behavior baseline tracking."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import cast

from app.schemas import ActionStats
from app.services.redis_service import get_redis_client

logger = logging.getLogger(__name__)

_BASELINE_TTL = 60 * 60 * 24 * 7


def _baseline_key(org_id: str, agent_id: str) -> str:
    return f"agent_baseline:{org_id}:{agent_id}"


def _anomaly_key(org_id: str, agent_id: str) -> str:
    return f"agent_anomalies:{org_id}:{agent_id}"


async def record_action(org_id: str, agent_id: str, action: str, resource: str) -> None:
    redis = get_redis_client()
    if redis is None:
        return
    try:
        key = _baseline_key(org_id, agent_id)
        anomaly_key = _anomaly_key(org_id, agent_id)
        await cast(Awaitable[object], redis.zincrby(key, 1, action))
        await redis.expire(key, _BASELINE_TTL)
        await cast(Awaitable[object], redis.sadd(anomaly_key, action))
        await redis.expire(anomaly_key, _BASELINE_TTL)
    except Exception as exc:
        logger.debug("Failed to record anomaly baseline for %s/%s: %s", org_id, agent_id, exc)


async def is_new_action(org_id: str, agent_id: str, action: str) -> bool:
    redis = get_redis_client()
    if redis is None:
        return False
    try:
        score = await redis.zscore(_baseline_key(org_id, agent_id), action)
        return score is None
    except Exception as exc:
        logger.debug("Failed to inspect anomaly baseline for %s/%s: %s", org_id, agent_id, exc)
        return False


async def get_action_baseline(org_id: str, agent_id: str) -> list[ActionStats]:
    redis = get_redis_client()
    if redis is None:
        return []
    try:
        rows = await redis.zrevrange(_baseline_key(org_id, agent_id), 0, -1, withscores=True)
        stats: list[ActionStats] = []
        for action, score in rows:
            stats.append(ActionStats(action=action, count=int(score)))
        return stats
    except Exception as exc:
        logger.debug("Failed to load anomaly baseline for %s/%s: %s", org_id, agent_id, exc)
        return []


async def get_recent_anomalies(org_id: str, agent_id: str) -> list[str]:
    redis = get_redis_client()
    if redis is None:
        return []
    try:
        anomaly_key = _anomaly_key(org_id, agent_id)
        actions_raw = await cast(
            Awaitable[set[object]],
            redis.smembers(anomaly_key),
        )
        baseline = await get_action_baseline(org_id, agent_id)
        one_off_actions = {item.action for item in baseline if item.count <= 1}
        actions = [action for action in actions_raw if isinstance(action, str)]
        return sorted(action for action in actions if action in one_off_actions)
    except Exception as exc:
        logger.debug("Failed to load anomaly flags for %s/%s: %s", org_id, agent_id, exc)
        return []
