"""Redis-backed agent behavior baseline tracking."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import cast

from app.schemas import ActionStats
from app.services.redis_service import get_redis_client

logger = logging.getLogger(__name__)

_BASELINE_TTL = 60 * 60 * 24 * 7

# W5.5 — behavioural anomaly tunables. The minimum-sample guard prevents the
# advisory from firing for agents that have just been registered (no baseline
# yet means every triple looks "unusual").
_TRIPLE_THRESHOLD = 0.85
_MIN_BASELINE_SAMPLES = 20


def _baseline_key(org_id: str, agent_id: str) -> str:
    return f"agent_baseline:{org_id}:{agent_id}"


def _anomaly_key(org_id: str, agent_id: str) -> str:
    return f"agent_anomalies:{org_id}:{agent_id}"


def _triple_baseline_key(org_id: str, agent_id: str) -> str:
    return f"agent_triple_baseline:{org_id}:{agent_id}"


def _triple_member(action: str, resource: str) -> str:
    return f"{action}::{resource}"


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


# ──────────────────────────────────────────────────────────────────────────────
# W5.5 — behavioural anomaly advisory
#
# The hardening plan calls for an embedding-based cosine distance between the
# current ``(agent_id, action, resource)`` and a trailing-30d distribution.
# Phase 1 ships a triple-frequency proxy: each unique ``action::resource`` pair
# the agent has invoked is tracked as a Redis ZSET member; the anomaly score is
# ``1 - p(triple)`` where ``p`` is the empirical probability over the last
# week (TTL-bounded). Triples unseen for that agent score 1.0; triples that
# dominate the agent's traffic score near 0. A bona-fide embedding back end
# (e.g. text-embedding-3-small + pgvector) can later be slotted in without
# changing the call sites — they only depend on ``triple_anomaly_score`` and
# ``behavioral_anomaly_finding``.
#
# The signal is purely advisory: it never blocks. It surfaces as a compliance
# finding with ``severity="info"`` and ``passed=True``, alongside the existing
# ``new_action`` flag.
# ──────────────────────────────────────────────────────────────────────────────


async def record_triple(org_id: str, agent_id: str, action: str, resource: str) -> None:
    """Increment the count for ``(action, resource)`` in the agent's baseline."""
    redis = get_redis_client()
    if redis is None:
        return
    try:
        key = _triple_baseline_key(org_id, agent_id)
        member = _triple_member(action, resource)
        await cast(Awaitable[object], redis.zincrby(key, 1, member))
        await redis.expire(key, _BASELINE_TTL)
    except Exception as exc:
        logger.debug("Failed to record triple baseline for %s/%s: %s", org_id, agent_id, exc)


async def triple_anomaly_score(org_id: str, agent_id: str, action: str, resource: str) -> float:
    """Return an anomaly score in ``[0.0, 1.0]`` for the given triple.

    Returns ``0.0`` (no signal) when:
      * Redis is unavailable, or
      * the agent's baseline has fewer than ``_MIN_BASELINE_SAMPLES`` events
        (too thin to draw an inference from).

    Otherwise returns ``1 - count(triple) / total_events`` for the agent's
    trailing-window baseline; novel triples score 1.0 and dominant triples
    score near 0.
    """
    redis = get_redis_client()
    if redis is None:
        return 0.0
    try:
        key = _triple_baseline_key(org_id, agent_id)
        member = _triple_member(action, resource)
        triple_score = await redis.zscore(key, member)
        triple_count = float(triple_score) if triple_score is not None else 0.0

        # Sum of all member scores → total observations for this agent.
        rows = await redis.zrange(key, 0, -1, withscores=True)
        total = 0.0
        for _member, score in rows:
            try:
                total += float(score)
            except (TypeError, ValueError):
                continue
        if total < _MIN_BASELINE_SAMPLES:
            return 0.0
        return max(0.0, 1.0 - (triple_count / total))
    except Exception as exc:
        logger.debug("Failed to score triple anomaly for %s/%s: %s", org_id, agent_id, exc)
        return 0.0


def _build_advisory_finding(
    agent_id: str, action: str, resource: str, score: float
) -> dict[str, object]:
    return {
        "plugin": "behavioral_anomaly",
        "plugin_id": "behavioral_anomaly",
        "standard": "INTERNAL",
        "rule_id": "ANOMALY-001",
        "severity": "info",
        "message": (
            f"Agent {agent_id!r} performed action={action!r} on resource={resource!r} "
            f"that is unusual relative to its trailing baseline "
            f"(anomaly_score={score:.2f})."
        ),
        "passed": True,
        "remediation_steps": [
            "Review the action in the audit log to confirm it is intentional.",
            "If expected, no action needed — the baseline self-updates over time.",
        ],
        "severity_level": "low",
        "compliance_score": 100,
    }


async def behavioral_anomaly_finding(
    org_id: str, agent_id: str, action: str, resource: str
) -> dict[str, object] | None:
    """Return an advisory compliance finding when the triple exceeds threshold.

    Never raises and never blocks; returns ``None`` when the score is below
    threshold or the baseline is too thin.
    """
    try:
        score = await triple_anomaly_score(org_id, agent_id, action, resource)
    except Exception:  # pragma: no cover — advisory is fail-quiet
        return None
    if score < _TRIPLE_THRESHOLD:
        return None
    return _build_advisory_finding(agent_id, action, resource, score)
